"""Payload utilities shared by the chat client."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

__all__ = ["build_payload"]


def _read_positive_int(raw: str) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def _read_positive_int_env(*names: str) -> int:
    for name in names:
        raw = os.getenv(name)
        if raw is None:
            continue
        value = _read_positive_int(raw)
        if value:
            return value
    return 0


def _detect_available_cpus() -> int:
    try:
        affinity = os.sched_getaffinity(0)  # type: ignore[attr-defined]
    except Exception:
        affinity = None
    if affinity:
        return len(affinity)
    return os.cpu_count() or 0


def _default_thread_cap() -> int:
    cap = _read_positive_int_env("NOX_NUM_THREADS_CAP")
    if cap:
        return cap
    if os.getenv("TERMUX_VERSION") or os.getenv("ANDROID_ROOT"):
        return 6
    return 0


def _messages_to_prompt(messages: List[Dict[str, Any]]) -> str:
    conversation_parts: List[str] = []

    dialogue: List[Dict[str, Any]] = [
        msg for msg in messages if (msg.get("role") or "").lower() in {"user", "assistant"}
    ]
    # keep the last three user/assistant exchanges (max six entries)
    max_items = 6
    if len(dialogue) > max_items:
        dialogue = dialogue[-max_items:]

    for msg in dialogue:
        role = (msg.get("role") or "").lower()
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            conversation_parts.append(f"<|user|>{content}")
        elif role == "assistant":
            conversation_parts.append(f"<|assistant|>{content}")

    conversation = "\n".join(conversation_parts).strip()
    if conversation and not conversation.endswith("<|assistant|>"):
        conversation = f"{conversation}\n<|assistant|>"
    elif not conversation:
        conversation = "<|assistant|>"

    return conversation


def _system_and_prompt(messages: List[Dict[str, Any]]) -> Tuple[str, str]:
    system_texts: List[str] = []
    for msg in messages:
        if (msg.get("role") or "").lower() == "system":
            content = str(msg.get("content") or "").strip()
            if content:
                system_texts.append(content)
    system_text = "\n\n".join(system_texts)

    prompt = _messages_to_prompt(messages)
    return system_text, prompt


def build_payload(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    max_tokens: int,
    stream: bool,
) -> Dict[str, Any]:
    """Return a payload compatible with Ollama's chat/generate APIs."""

    options: Dict[str, Any] = {"temperature": temperature}

    threads = _read_positive_int_env("NOX_NUM_THREADS", "NOX_NUM_THREAD")
    if threads:
        options["num_thread"] = threads
    else:
        detected = _detect_available_cpus()
        cap = _default_thread_cap()
        if detected and cap:
            detected = min(detected, cap)
        if detected:
            options["num_thread"] = detected

    num_ctx = _read_positive_int_env(
        "NOX_NUM_CTX",
        "NOX_CONTEXT_LENGTH",
        "NOX_CONTEXT_LEN",
        "OLLAMA_CONTEXT_LENGTH",
    )
    if num_ctx:
        options["num_ctx"] = num_ctx

    num_batch = _read_positive_int_env("NOX_NUM_BATCH")
    if num_batch:
        options["num_batch"] = num_batch

    if max_tokens and max_tokens > 0:
        options["num_predict"] = max_tokens

    system_text, prompt = _system_and_prompt(messages)
    payload: Dict[str, Any] = {
        "model": model,
        "stream": stream,
        "options": options,
    }

    keep_alive = (
        os.getenv("NOX_KEEP_ALIVE")
        or os.getenv("NOX_OLLAMA_KEEP_ALIVE")
        or os.getenv("OLLAMA_KEEP_ALIVE")
        or ""
    ).strip()
    if keep_alive:
        payload["keep_alive"] = keep_alive

    if prompt:
        payload["prompt"] = prompt
    if system_text:
        payload["system"] = system_text

    # include chat-style messages for endpoints that support them
    if messages:
        payload["messages"] = messages
    return payload
