"""Anthropic instrument implementation using the official SDK."""

from __future__ import annotations

from contextlib import suppress
from typing import Any, Dict, Iterable, List, Optional

from .base import (
    BaseInstrument,
    ChunkCallback,
    InstrumentDependencyError,
    InstrumentResponse,
    InstrumentSetupError,
)
from . import register_instrument


def _flatten_messages(messages: Iterable[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]]]:
    system_parts: List[str] = []
    formatted: List[Dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user").lower()
        text = BaseInstrument._flatten_text_content(message.get("content"))
        if not text:
            continue
        if role == "system":
            system_parts.append(text)
            continue
        if role not in {"user", "assistant"}:
            continue
        formatted.append({"role": role, "content": [{"type": "text", "text": text}]})
    system_prompt = "\n\n".join(system_parts) if system_parts else ""
    return system_prompt, formatted


def _collect_text_from_content(content: Any) -> str:
    pieces: List[str] = []
    if isinstance(content, list):
        for block in content:
            text = getattr(block, "text", None)
            if text is None and isinstance(block, dict):
                text = block.get("text")
            if isinstance(text, str):
                pieces.append(text)
    else:
        text = getattr(content, "text", None) or (content.get("text") if isinstance(content, dict) else None)  # type: ignore[arg-type]
        if isinstance(text, str):
            pieces.append(text)
    return "".join(pieces)


class AnthropicInstrument(BaseInstrument):
    """Instrument that sends chat requests through the Anthropic SDK."""

    name = "anthropic"

    def __init__(self, *, url: Optional[str], model: Optional[str], api_key: Optional[str]) -> None:
        super().__init__(url=url, model=model, api_key=api_key)
        if not self.api_key:
            raise InstrumentSetupError("Anthropic instrument requires an API key.")
        try:
            from anthropic import Anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency missing
            raise InstrumentDependencyError(
                "Anthropic instrument requires the 'anthropic' package (pip install anthropic)."
            ) from exc
        self._client = Anthropic(api_key=self.api_key)

    @classmethod
    def matches(cls, *, url: Optional[str], model: Optional[str]) -> bool:
        url_l = (url or "").lower()
        model_l = (model or "").lower()
        if "anthropic" in url_l:
            return True
        if model_l.startswith("claude") or model_l.startswith("haiku") or model_l.startswith("sonnet"):
            return True
        return False

    def _build_args(
        self,
        messages: Iterable[Dict[str, Any]],
        *,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> Dict[str, Any]:
        system_prompt, formatted = _flatten_messages(messages)
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": formatted,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens and max_tokens > 0:
            kwargs["max_tokens"] = max_tokens
        return kwargs

    def send_chat(
        self,
        messages: Iterable[Dict[str, Any]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        on_chunk: Optional[ChunkCallback] = None,
    ) -> InstrumentResponse:
        kwargs = self._build_args(messages, temperature=temperature, max_tokens=max_tokens)
        if stream:
            return self._send_streaming(kwargs, on_chunk=on_chunk)
        return self._send_normal(kwargs)

    def _send_normal(self, kwargs: Dict[str, Any]) -> InstrumentResponse:
        response = self._client.messages.create(**kwargs)
        content = getattr(response, "content", None)
        text = _collect_text_from_content(content)
        raw = None
        with suppress(Exception):
            raw = response.model_dump()  # type: ignore[attr-defined]
        return InstrumentResponse(text, raw=raw if isinstance(raw, dict) else None)

    def _send_streaming(
        self,
        kwargs: Dict[str, Any],
        *,
        on_chunk: Optional[ChunkCallback],
    ) -> InstrumentResponse:
        stream_handle = self._client.messages.stream(**kwargs)
        pieces: List[str] = []
        with stream_handle as events:
            for event in events:
                event_type = getattr(event, "type", "")
                if event_type == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    chunk = getattr(delta, "text", None)
                    if chunk:
                        pieces.append(chunk)
                        if on_chunk:
                            on_chunk(chunk)
                elif event_type == "message_delta":
                    delta = getattr(event, "delta", None)
                    text = getattr(delta, "text", None)
                    if text:
                        pieces.append(text)
                        if on_chunk:
                            on_chunk(text)
            final_response = events.get_final_response()
        content = getattr(final_response, "content", None)
        text = "".join(pieces) or _collect_text_from_content(content)
        raw = None
        with suppress(Exception):
            raw = final_response.model_dump()  # type: ignore[attr-defined]
        return InstrumentResponse(text, raw=raw if isinstance(raw, dict) else None)


register_instrument(AnthropicInstrument)

__all__ = ["AnthropicInstrument"]
