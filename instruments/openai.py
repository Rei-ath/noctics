"""OpenAI instrument implementation using the official SDK."""

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


def _maybe_model_dump(obj: Any) -> Optional[Dict[str, Any]]:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    for attr in ("model_dump", "to_dict", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return dict(fn())
            except Exception:
                continue
    with suppress(Exception):
        return dict(obj.__dict__)  # type: ignore[arg-type]
    return None


def _normalise_event_text(event: Any) -> Optional[str]:
    if event is None:
        return None
    text = getattr(event, "delta", None)
    if isinstance(text, str) and text:
        return text
    if isinstance(text, dict):
        candidate = text.get("text")
        if isinstance(candidate, str) and candidate:
            return candidate
    data = getattr(event, "data", None)
    if isinstance(data, str) and data:
        return data
    if isinstance(event, dict):
        for key in ("delta", "text", "data"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict):
                candidate = value.get("text")
                if isinstance(candidate, str) and candidate:
                    return candidate
    return None


def _collect_response_text(response: Any) -> str:
    # Responses API objects expose ``output`` and/or ``output_text``
    if response is None:
        return ""
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text:
        return output_text
    pieces: List[str] = []
    output = getattr(response, "output", None)
    if isinstance(output, list):
        for item in output:
            item_type = getattr(item, "type", None)
            if not item_type and isinstance(item, dict):
                item_type = item.get("type")
            if item_type != "output_text":
                continue
            content = getattr(item, "content", None)
            if content is None and isinstance(item, dict):
                content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                text = getattr(part, "text", None)
                if text is None and isinstance(part, dict):
                    text = part.get("text")
                if isinstance(text, str):
                    pieces.append(text)
    if pieces:
        return "".join(pieces)
    dumped = _maybe_model_dump(response) or {}
    for item in dumped.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "output_text":
            continue
        for part in item.get("content", []) or []:
            text = part.get("text") if isinstance(part, dict) else None
            if isinstance(text, str):
                pieces.append(text)
    return "".join(pieces)


class OpenAIInstrument(BaseInstrument):
    """Instrument that sends chat requests through the OpenAI SDK."""

    name = "openai"

    def __init__(self, *, url: Optional[str], model: Optional[str], api_key: Optional[str]) -> None:
        super().__init__(url=url, model=model, api_key=api_key)
        if not self.api_key:
            raise InstrumentSetupError("OpenAI instrument requires an API key.")
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency missing
            raise InstrumentDependencyError(
                "OpenAI instrument requires the 'openai' package (pip install openai>=1.0)."
            ) from exc
        self._client = OpenAI(api_key=self.api_key)

    # Registry matching --------------------------------------------------
    @classmethod
    def matches(cls, *, url: Optional[str], model: Optional[str]) -> bool:
        url_l = (url or "").lower()
        model_l = (model or "").lower()
        if "openai" in url_l:
            return True
        if model_l.startswith(("gpt", "o1")):
            return True
        return False

    # Routing helpers ----------------------------------------------------
    def _use_responses_api(self) -> bool:
        model_l = self.model.lower()
        return model_l.startswith(("gpt-4.1", "gpt-4o", "gpt-5", "o1"))

    def _format_chat_messages(self, messages: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
        formatted: List[Dict[str, str]] = []
        for message in messages:
            role = str(message.get("role", "user"))
            content = self._flatten_text_content(message.get("content"))
            formatted.append({"role": role, "content": content})
        return formatted

    def _format_response_input(self, messages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        formatted: List[Dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role", "user"))
            content = message.get("content")
            if isinstance(content, list):
                parts: List[Dict[str, Any]] = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text" and "text" in item:
                            parts.append({"type": "text", "text": str(item["text"])})
                        else:
                            parts.append({"type": "text", "text": str(item)})
                    elif item is not None:
                        parts.append({"type": "text", "text": str(item)})
                if not parts:
                    parts.append({"type": "text", "text": ""})
                formatted.append({"role": role, "content": parts})
                continue
            formatted.append({"role": role, "content": [{"type": "text", "text": self._flatten_text_content(content)}]})
        return formatted

    # Public API ---------------------------------------------------------
    def send_chat(
        self,
        messages: Iterable[Dict[str, Any]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        on_chunk: Optional[ChunkCallback] = None,
    ) -> InstrumentResponse:
        if self._use_responses_api():
            return self._send_via_responses(messages, temperature, max_tokens, stream, on_chunk)
        return self._send_via_chat(messages, temperature, max_tokens, stream, on_chunk)

    # Chat Completions ---------------------------------------------------
    def _send_via_chat(
        self,
        messages: Iterable[Dict[str, Any]],
        temperature: Optional[float],
        max_tokens: Optional[int],
        stream: bool,
        on_chunk: Optional[ChunkCallback],
    ) -> InstrumentResponse:
        formatted = self._format_chat_messages(messages)
        max_tokens_kw = max_tokens if max_tokens and max_tokens > 0 else None
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": formatted,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens_kw is not None:
            kwargs["max_tokens"] = max_tokens_kw
        if stream:
            kwargs["stream"] = True
            stream_iter = self._client.chat.completions.create(**kwargs)
            pieces: List[str] = []
            for chunk in stream_iter:
                choice = (chunk.choices or [None])[0]
                delta = getattr(choice, "delta", None)
                content = getattr(delta, "content", None)
                if content:
                    if on_chunk:
                        on_chunk(content)
                    pieces.append(content)
            return InstrumentResponse("".join(pieces))

        completion = self._client.chat.completions.create(**kwargs)
        choice = (completion.choices or [None])[0]
        message = getattr(choice, "message", None)
        text = getattr(message, "content", None)
        raw = _maybe_model_dump(completion)
        return InstrumentResponse(text, raw=raw)

    # Responses API ------------------------------------------------------
    def _send_via_responses(
        self,
        messages: Iterable[Dict[str, Any]],
        temperature: Optional[float],
        max_tokens: Optional[int],
        stream: bool,
        on_chunk: Optional[ChunkCallback],
    ) -> InstrumentResponse:
        formatted = self._format_response_input(messages)
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "input": formatted,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens and max_tokens > 0:
            kwargs["max_output_tokens"] = max_tokens
        if stream:
            stream_obj = self._client.responses.stream(**kwargs)
            pieces: List[str] = []
            with stream_obj as events:
                for event in events:
                    if getattr(event, "type", "") == "response.output_text.delta":
                        piece = _normalise_event_text(event)
                        if piece:
                            pieces.append(piece)
                            if on_chunk:
                                on_chunk(piece)
                final_response = events.get_final_response()
            raw = _maybe_model_dump(final_response)
            text = "".join(pieces) or _collect_response_text(final_response)
            return InstrumentResponse(text, raw=raw)

        response = self._client.responses.create(**kwargs)
        raw = _maybe_model_dump(response)
        text = _collect_response_text(response)
        return InstrumentResponse(text, raw=raw)


__all__ = ["OpenAIInstrument"]
