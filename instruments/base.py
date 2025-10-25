"""Base classes and utilities for Central instruments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


class InstrumentError(RuntimeError):
    """Base exception for instrument-related failures."""


class InstrumentSetupError(InstrumentError):
    """Raised when an instrument cannot be initialised for the target."""


class InstrumentDependencyError(InstrumentSetupError):
    """Raised when required third-party dependencies are unavailable."""


ChunkCallback = Callable[[str], None]


@dataclass(slots=True)
class InstrumentResponse:
    """Standard response payload returned by instruments."""

    text: Optional[str]
    raw: Optional[Dict[str, Any]] = None


class BaseInstrument:
    """Common interface for SDK-backed instruments."""

    name: str = "instrument"

    def __init__(self, *, url: Optional[str], model: Optional[str], api_key: Optional[str]) -> None:
        self.url = url or ""
        self.model = model or ""
        self.api_key = api_key

    @classmethod
    def matches(cls, *, url: Optional[str], model: Optional[str]) -> bool:
        return False

    @classmethod
    def maybe_create(
        cls,
        *,
        url: Optional[str],
        model: Optional[str],
        api_key: Optional[str],
    ) -> Tuple[Optional["BaseInstrument"], Optional[str]]:
        if not cls.matches(url=url, model=model):
            return None, None
        try:
            return cls(url=url, model=model, api_key=api_key), None
        except InstrumentDependencyError as exc:
            return None, str(exc)
        except InstrumentSetupError as exc:
            return None, str(exc)

    def send_chat(
        self,
        messages: Iterable[Dict[str, Any]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        on_chunk: Optional[ChunkCallback] = None,
    ) -> InstrumentResponse:
        raise NotImplementedError

    # Utility routines ----------------------------------------------------
    @staticmethod
    def _flatten_text_content(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text" and "text" in item:
                        parts.append(str(item["text"]))
                    else:
                        parts.append(str(item))
                elif item is not None:
                    parts.append(str(item))
            return "".join(parts)
        return str(content)

    @staticmethod
    def _dedupe_sequence(items: Iterable[str]) -> List[str]:
        seen: set[str] = set()
        result: List[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result


__all__ = [
    "BaseInstrument",
    "InstrumentError",
    "InstrumentSetupError",
    "InstrumentDependencyError",
    "InstrumentResponse",
    "ChunkCallback",
]
