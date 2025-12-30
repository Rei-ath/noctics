"""Chat client implementation for Nox."""

from __future__ import annotations

import logging
import os
import socket
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional
from urllib.error import URLError
from urllib.parse import urlparse

from interfaces.dotenv import load_local_dotenv
from interfaces.pii import sanitize as pii_sanitize
from interfaces.session_logger import SessionLogger
from noxl import (
    append_session_to_day_log as noxl_append_session_to_day_log,
    compute_title_from_messages,
    delete_session_if_empty as noxl_delete_session_if_empty,
)

from ..transport import LLMTransport
from ..connector import NoxConnector, build_connector
from ..persona import resolve_persona
from .instrument_prompt import load_instrument_prompt
from .payloads import build_payload
from .reasoning import clean_public_reply, extract_public_segments, strip_chain_of_thought
from nox_env import get_env, require_env

try:  # instruments package lives in the superproject
    from instruments import build_instrument as _build_instrument
except Exception:  # pragma: no cover - optional dependency
    _build_instrument = None

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from instruments.base import BaseInstrument

DEFAULT_URL = "http://127.0.0.1:11434/api/chat"


class ChatClient:
    """Stateful chat client used by the CLI and external consumers."""

    DEFAULT_URL: str = DEFAULT_URL

    def __init__(
        self,
        *,
        url: str | None = None,
        model: str | None = None,
        api_key: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = -1,
        stream: bool = False,
        sanitize: bool = False,
        messages: Optional[List[Dict[str, Any]]] = None,
        enable_logging: bool = True,
        strip_reasoning: bool = True,
        memory_user: Optional[str] = None,
        memory_user_display: Optional[str] = None,
        transport: Optional[LLMTransport] = None,
        connector: Optional[NoxConnector] = None,
    ) -> None:
        if os.getenv("PYTEST_CURRENT_TEST") is None and os.getenv("NOCTICS_SKIP_DOTENV") != "1":
            try:
                load_local_dotenv(Path(__file__).resolve().parent)
            except Exception:
                pass

        resolved_url = url or get_env("NOX_LLM_URL")

        resolved_api_key = api_key or (get_env("NOX_LLM_API_KEY") or os.getenv("OPENAI_API_KEY"))

        connector = connector or build_connector(url=resolved_url, api_key=resolved_api_key)
        self.connector = connector

        if transport is None:
            transport = connector.connect()

        self.transport = transport
        resolved_url = getattr(transport, "url", resolved_url)
        resolved_api_key = getattr(transport, "api_key", resolved_api_key)

        self.url = resolved_url
        self.model = model or require_env("NOX_LLM_MODEL")
        self.target_model = self._select_target_model(resolved_url, self.model)
        self.api_key = resolved_api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stream = stream
        self.sanitize = sanitize
        self.messages: List[Dict[str, Any]] = list(messages or [])
        self.strip_reasoning = strip_reasoning
        self.persona = resolve_persona(self.model)
        self.last_instrument_error: Optional[str] = None

        self.logger = (
            SessionLogger(
                model=self.model,
                sanitized=bool(self.sanitize),
                user_id=memory_user,
                user_display=memory_user_display,
            )
            if enable_logging
            else None
        )
        if self.logger:
            self.logger.start()

        self.instrument: Optional["BaseInstrument"] = None
        self.instrument_warning: Optional[str] = None
        if _build_instrument is not None:
            try:
                instrument, warning = _build_instrument(
                    url=self.url,
                    model=self.target_model,
                    api_key=self.api_key,
                )
            except Exception:  # pragma: no cover - defensive fallback
                instrument, warning = None, None
            self.instrument = instrument
            self.instrument_warning = warning

    # -----------------
    # Internal helpers
    # -----------------
    def _sanitize_user_text(self, text: str) -> str:
        """Apply PII scrubbing when the client runs in sanitize mode."""

        return pii_sanitize(text) if self.sanitize else text

    def _log_turn(self, user_content: str, assistant_content: str) -> None:
        """Persist a turn to the session log, including the active system prompt."""

        if not self.logger:
            return
        sys_msgs = [m for m in self.messages if m.get("role") == "system"]
        to_log = (sys_msgs[-1:] if sys_msgs else []) + [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ]
        self.logger.log_turn(to_log)

    def _append_turn(self, user_content: str, assistant_content: str) -> None:
        """Append the latest user/assistant exchange to memory and logs."""

        self.messages.append({"role": "user", "content": user_content})
        self.messages.append({"role": "assistant", "content": assistant_content})
        self._log_turn(user_content, assistant_content)

    def _call_instrument(
        self,
        messages: List[Dict[str, Any]],
        *,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Try the automation instrument first, returning (reply, error)."""

        if self.instrument is None:
            return None, None
        try:
            instrument_response = self.instrument.send_chat(
                messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens if self.max_tokens and self.max_tokens > 0 else None,
                stream=bool(self.stream),
                on_chunk=on_chunk,
            )
        except Exception as exc:  # pragma: no cover - defensive production fallback
            error = f"Instrument '{getattr(self.instrument, 'name', 'unknown')}' failed: {exc}"
            self.last_instrument_error = error
            _LOGGER.warning(error)
            return None, error
        return instrument_response.text, None

    def _dispatch_payload(
        self,
        payload: Dict[str, Any],
        *,
        stream: bool,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> tuple[Optional[str], Any]:
        """Send payload through the configured transport."""

        if stream:
            return self.transport.send(payload, stream=True, on_chunk=on_chunk)
        return self.transport.send(payload, stream=False)

    @staticmethod
    def _select_target_model(url: str, model: str) -> str:
        override = get_env("NOX_TARGET_MODEL")
        if override:
            return override

        url_lower = (url or "").lower()
        model_lower = (model or "").lower()

        if "api.openai.com" in url_lower:
            if model_lower in {"nox", "nox:latest"}:
                return get_env("NOX_OPENAI_MODEL") or "gpt-4o-mini"
            if model_lower in {"gpt-5"}:
                return get_env("NOX_OPENAI_MODEL") or "gpt-4o-mini"
            return model

        return model

    # -----------------
    # Payload adapters
    # -----------------
    def _prepare_payload(self, payload: Dict[str, Any], *, stream: bool) -> Dict[str, Any]:
        """Normalize payload details for specific providers."""

        target_url = (self.url or "").lower()
        if "openai.com" not in target_url:
            return payload
        adjusted: Dict[str, Any] = {"model": self.target_model, "messages": []}

        system_text = payload.get("system")
        if system_text:
            adjusted["messages"].append({"role": "system", "content": str(system_text)})

        def _flatten_content(content: Any) -> str:
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if text is not None:
                            parts.append(str(text))
                        else:
                            parts.append(str(item))
                    elif item is not None:
                        parts.append(str(item))
                return "\n".join(parts)
            if content is None:
                return ""
            return str(content)

        for message in payload.get("messages") or []:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "user")
            content = _flatten_content(message.get("content"))
            adjusted["messages"].append({"role": role, "content": content})

        if not adjusted["messages"]:
            adjusted["messages"] = [{"role": "user", "content": ""}]

        if self.temperature is not None:
            adjusted["temperature"] = self.temperature
        if self.max_tokens and self.max_tokens > 0:
            adjusted["max_tokens"] = self.max_tokens
        if stream:
            adjusted["stream"] = True

        return adjusted

    # ---------------------
    # Connectivity / health
    # ---------------------
    def check_connectivity(self, *, timeout: float = 1.0) -> None:
        """Raise ``URLError`` if the configured endpoint is unreachable."""

        parsed = urlparse(self.url)
        host = parsed.hostname
        if not host:
            raise URLError(f"Invalid NOX_LLM_URL (no host): {self.url}")

        port = parsed.port or (443 if (parsed.scheme or "http").lower() == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return
        except Exception as exc:  # pragma: no cover - requires network issues
            message = f"Unable to connect to Nox at {host}:{port} ({type(exc).__name__}: {exc})."
            raise URLError(message)

    # ---------------------
    # Message/state utilities
    # ---------------------
    def reset_messages(self, system: Optional[str] = None) -> None:
        self.messages = []
        if system:
            self.messages.append({"role": "system", "content": system})

    def set_messages(self, messages: List[Dict[str, Any]]) -> None:
        self.messages = list(messages)

    # ---------------------
    # Session title utilities
    # ---------------------
    def get_session_title(self) -> Optional[str]:
        if not self.logger:
            return None
        meta = self.logger.get_meta()
        return meta.get("title")

    def set_session_title(self, title: str, *, custom: bool = True) -> None:
        if not self.logger:
            return
        self.logger.set_title(title, custom=custom)

    def ensure_auto_title(self) -> Optional[str]:
        """Ensure a session title exists; compute and set one if absent."""

        if not self.logger:
            return None
        meta = self.logger.get_meta()
        if meta.get("title") and meta.get("custom"):
            return meta.get("title")

        title = compute_title_from_messages(self.messages) or meta.get("title")
        if title:
            self.logger.set_title(title, custom=False)
        return title

    # ----------------------
    # Instrument detection
    # ----------------------
    @staticmethod
    def wants_instrument(text: Optional[str]) -> bool:
        """Return True if the assistant text indicates an external instrument is needed."""
        if not text:
            return False
        lowered = text.lower()
        return ("[instrument query]" in lowered) or ("requires an instrument" in lowered)

    # -------------
    # Public API
    # -------------
    def one_turn(
        self,
        user_text: str,
        *,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        to_send_user = self._sanitize_user_text(user_text)
        turn_messages = self.messages + [{"role": "user", "content": to_send_user}]
        stream_callback = on_delta
        public_state: Dict[str, Any] = {}
        if self.stream:
            if self.strip_reasoning and on_delta:
                public_state = {"buffer": "", "public": ""}

                def sanitized_delta(piece: str) -> None:
                    state = public_state
                    buffer = state["buffer"] + piece
                    public, remainder = extract_public_segments(buffer)
                    state["buffer"] = remainder
                    previous = state["public"]
                    if len(public) > len(previous):
                        on_delta(public[len(previous):])
                        state["public"] = public

                stream_callback = sanitized_delta

        assistant: Optional[str] = None

        assistant, instrument_error = self._call_instrument(turn_messages, on_chunk=stream_callback)

        if assistant is None:
            payload = build_payload(
                model=self.target_model,
                messages=turn_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=bool(self.stream),
            )
            payload = self._prepare_payload(payload, stream=bool(self.stream))

            assistant, _ = self._dispatch_payload(
                payload,
                stream=bool(self.stream),
                on_chunk=stream_callback,
            )
            if instrument_error:
                self.instrument_warning = instrument_error

        if assistant is not None:
            if self.strip_reasoning:
                assistant = strip_chain_of_thought(assistant)
                if (
                    self.stream
                    and on_delta
                    and public_state
                    and self.instrument is None
                ):
                    public_text = public_state.get("public", "")
                    if len(assistant) > len(public_text):
                        on_delta(assistant[len(public_text):])
            assistant = clean_public_reply(assistant) or ""
            self._append_turn(to_send_user, assistant)
        return assistant

    def record_turn(self, user_text: str, assistant_text: str) -> None:
        """Record an assistant response without calling the API."""

        to_send_user = self._sanitize_user_text(user_text)
        if self.strip_reasoning:
            assistant_text = strip_chain_of_thought(assistant_text)
        assistant_text = clean_public_reply(assistant_text) or ""
        self._append_turn(to_send_user, assistant_text)

    def process_instrument_result(
        self,
        instrument_text: str,
        *,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        if not instrument_text:
            return None
        instrument_wrapped = f"[INSTRUMENT RESULT]\n{instrument_text}\n[/INSTRUMENT RESULT]"
        instrument_messages = list(self.messages)
        instrument_messages.append({"role": "system", "content": load_instrument_prompt()})
        instrument_messages.append({"role": "user", "content": instrument_wrapped})
        reply: Optional[str] = None
        reply, instrument_error = self._call_instrument(instrument_messages, on_chunk=on_delta)

        if reply is None:
            payload = build_payload(
                model=self.model,
                messages=instrument_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=bool(self.stream),
            )
            payload = self._prepare_payload(payload, stream=bool(self.stream))

            reply, _ = self._dispatch_payload(
                payload,
                stream=bool(self.stream),
                on_chunk=on_delta,
            )
            if instrument_error:
                self.instrument_warning = instrument_error

        if reply is not None:
            if self.strip_reasoning:
                reply = strip_chain_of_thought(reply)
            reply = clean_public_reply(reply) or ""
            self._append_turn(instrument_wrapped, reply)
        return reply

    # -----------------
    # Diagnostics / info
    # -----------------
    def describe_target(self) -> Dict[str, Any]:
        """Return a sanitized snapshot of the configured target LLM."""

        return {
            "url": self.url,
            "model": self.model,
            "central_name": getattr(self.persona, "central_name", None),
            "central_scale": getattr(self.persona, "scale", None),
            "noctics_variant": getattr(self.persona, "variant_name", None),
            "model_target": getattr(self.persona, "model_target", None),
            "stream": bool(self.stream),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "sanitize": bool(self.sanitize),
            "strip_reasoning": bool(self.strip_reasoning),
            "logging_enabled": self.logger is not None,
            "target_model": self.target_model,
            "has_api_key": bool(self.api_key),
            "instrument": getattr(self.instrument, "name", None),
            "instrument_warning": self.instrument_warning,
        }

    def log_path(self) -> Optional[Path]:
        """Return the current session log file path, if logging is enabled."""

        if not self.logger:
            return None
        return self.logger._file

    def maybe_delete_empty_session(self) -> bool:
        if not self.logger:
            return False
        path = self.logger.log_path()
        if not path or not path.exists():
            return False
        meta_path = self.logger.meta_path()
        return noxl_delete_session_if_empty(path, meta_path=meta_path)

    def append_session_to_day_log(self) -> Optional[Path]:
        if not self.logger:
            return None
        log_path = self.logger.log_path()
        if not log_path or not log_path.exists():
            return None
        meta = self.logger.get_meta()
        return noxl_append_session_to_day_log(log_path, meta=meta)

    def adopt_session_log(self, log_path: Path) -> None:
        if not self.logger:
            return
        self.logger.load_existing(log_path)


__all__ = ["ChatClient", "DEFAULT_URL"]
_LOGGER = logging.getLogger("noctics.chat")
