"""Transport utilities for Nox's ChatClient."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProcessTransport:
    """Spawn a local runner binary and stream stdout directly (no HTTP)."""

    def __init__(self, binary: str, model_path: Optional[str] = None) -> None:
        self.binary = binary
        self.model_path = model_path
        self.url = None
        self.api_key = None

    def send(
        self,
        payload: Dict[str, Any],
        *,
        stream: bool = False,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        prompt = _payload_to_prompt(payload)
        if not prompt:
            raise URLError("No prompt content found for local runner payload.")

        max_tokens = int(payload.get("max_tokens", 128) or 128)
        ctx = int(payload.get("num_ctx", 1024) or 1024)
        num_threads = int(os.getenv("NOX_NUM_THREADS", "0") or "0")
        args = [
            self.binary,
            "-raw",
            "-max-tokens",
            str(max_tokens),
            "-ctx",
            str(ctx),
        ]
        if self.model_path:
            args.extend(["-model", self.model_path])
        args.append(prompt)

        env = dict(os.environ)
        env.setdefault("NOX_NUM_THREADS", str(num_threads or 0))

        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:  # pragma: no cover - subprocess setup errors
            raise URLError(f"Failed to launch local runner {self.binary}: {exc}") from exc

        acc: list[str] = []
        if proc.stdout:
            if stream:
                for chunk in iter(lambda: proc.stdout.read(1), ""):
                    if chunk:
                        acc.append(chunk)
                        if on_chunk:
                            on_chunk(chunk)
            else:
                acc.append(proc.stdout.read())

        stdout_text = "".join(acc)
        stderr_text = proc.stderr.read() if proc.stderr else ""
        code = proc.wait()
        if code != 0:
            raise URLError(
                f"Local runner exited with code {code}: {stderr_text.strip() or stdout_text}"
            )

        return stdout_text, {"stderr": stderr_text}


class LLMTransport:
    """Thin wrapper around HTTP requests to the configured LLM endpoint."""

    def __init__(self, url: str, api_key: Optional[str] = None) -> None:
        self.url = url
        self.api_key = api_key

    def send(
        self,
        payload: Dict[str, Any],
        *,
        stream: bool = False,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        send_payload = dict(payload)
        if "/api/generate" in self.url:
            send_payload.pop("messages", None)
        if "/api/chat" in self.url:
            send_payload.pop("prompt", None)
            send_payload.pop("system", None)
        data = json.dumps(send_payload).encode("utf-8")
        headers = self._headers(stream=stream)
        req = Request(self.url, data=data, headers=headers, method="POST")
        if "/api/generate" in self.url:
            if stream:
                text = self._stream_generate(req, on_chunk)
                return text, None
            return self._request_generate(req)
        if "/api/chat" in self.url:
            if stream:
                text = self._stream_ollama_chat(req, on_chunk)
                return text, None
            return self._request_ollama_chat(req)
        if stream:
            text = self._stream_sse(req, on_chunk)
            return text, None
        return self._request_json(req)

    # -----------------
    # Internal utilities
    # -----------------
    def _headers(self, *, stream: bool = False) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if stream:
            headers.setdefault("Accept", "text/event-stream")
        return headers

    def _request_json(self, req: Request) -> Tuple[Optional[str], Dict[str, Any]]:
        try:
            with urlopen(req) as resp:  # nosec - local/dev usage
                charset = resp.headers.get_content_charset() or "utf-8"
                body = resp.read().decode(charset)
        except HTTPError as he:  # pragma: no cover - network specific
            body = _extract_error_body(he)
            message = _http_error_message(he, suffix=body)
            raise HTTPError(req.full_url, he.code, message, he.headers, he.fp)
        except URLError as ue:  # pragma: no cover - network specific
            raise URLError(f"Failed to reach Nox at {self.url}: {ue.reason}")
        except OSError as oe:  # pragma: no cover - network specific
            raise URLError(f"Network error talking to Nox at {self.url}: {oe}")

        try:
            obj = json.loads(body)
        except Exception as exc:
            raise URLError(
                f"Nox returned non-JSON response: {exc}\nBody: {body[:512]}"
            ) from exc  # pragma: no cover

        message: Optional[str]
        try:
            message = obj["choices"][0]["message"].get("content")
        except Exception:
            message = None
        return message, obj

    def _request_generate(self, req: Request) -> Tuple[Optional[str], Dict[str, Any]]:
        try:
            with urlopen(req) as resp:  # nosec - local/dev usage
                charset = resp.headers.get_content_charset() or "utf-8"
                body = resp.read().decode(charset)
        except HTTPError as he:
            body = _extract_error_body(he)
            message = _http_error_message(he, suffix=body)
            raise HTTPError(req.full_url, he.code, message, he.headers, he.fp)
        except URLError as ue:
            raise URLError(f"Failed to reach Nox at {self.url}: {ue.reason}")
        except OSError as oe:
            raise URLError(f"Network error talking to Nox at {self.url}: {oe}")

        lines = [line for line in body.splitlines() if line.strip()]
        responses: list[str] = []
        payloads: list[Dict[str, Any]] = []
        for line in lines:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            payloads.append(data)
            if data.get("error"):
                raise URLError(str(data["error"]))
            text = data.get("response") or ""
            if text:
                responses.append(text)
        return ("".join(responses) if responses else None, {"responses": payloads})

    def _request_ollama_chat(self, req: Request) -> Tuple[Optional[str], Dict[str, Any]]:
        try:
            with urlopen(req) as resp:  # nosec - local/dev usage
                charset = resp.headers.get_content_charset() or "utf-8"
                body = resp.read().decode(charset)
        except HTTPError as he:  # pragma: no cover - network specific
            body = _extract_error_body(he)
            message = _http_error_message(he, suffix=body)
            raise HTTPError(req.full_url, he.code, message, he.headers, he.fp)
        except URLError as ue:  # pragma: no cover - network specific
            raise URLError(f"Failed to reach Nox at {self.url}: {ue.reason}")
        except OSError as oe:  # pragma: no cover - network specific
            raise URLError(f"Network error talking to Nox at {self.url}: {oe}")

        try:
            obj = json.loads(body)
        except Exception as exc:
            raise URLError(
                f"Nox returned non-JSON response: {exc}\nBody: {body[:512]}"
            ) from exc  # pragma: no cover

        if isinstance(obj, dict) and obj.get("error"):
            raise URLError(str(obj["error"]))

        message: Optional[str] = None
        if isinstance(obj, dict):
            msg = obj.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    message = content
            if message is None:
                content = obj.get("response")
                if isinstance(content, str):
                    message = content

        return message, obj

    def _stream_sse(
        self,
        req: Request,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        try:
            with urlopen(req) as resp:  # nosec - local/dev usage
                charset = resp.headers.get_content_charset() or "utf-8"
                buffer: list[str] = []
                acc: list[str] = []
                while True:
                    line_bytes = resp.readline()
                    if not line_bytes:
                        break
                    line = line_bytes.decode(charset, errors="replace").rstrip("\r\n")

                    if not line:
                        if not buffer:
                            continue
                        data_str = "\n".join(buffer).strip()
                        buffer.clear()
                        if not data_str:
                            continue
                        if data_str == "[DONE]":
                            break
                        piece = _extract_sse_piece(data_str)
                        if piece:
                            if on_chunk:
                                on_chunk(piece)
                            acc.append(piece)
                        continue

                    if line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        buffer.append(line[len("data:"):].lstrip())
                        continue
                    buffer.clear()
        except HTTPError as he:  # pragma: no cover - network specific
            message = _http_error_message(he)
            raise HTTPError(req.full_url, he.code, message, he.headers, he.fp)
        except URLError as ue:  # pragma: no cover - network specific
            raise URLError(f"Failed to reach Nox at {self.url}: {ue.reason}")
        except OSError as oe:  # pragma: no cover - network specific
            raise URLError(f"Network error talking to Nox at {self.url}: {oe}")

        return "".join(acc)


def _payload_to_prompt(payload: Dict[str, Any]) -> str:
    if "prompt" in payload and payload["prompt"]:
        return str(payload["prompt"])

    messages = payload.get("messages") or []
    if not isinstance(messages, list):
        return ""

    pieces: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role") or "user"
        content = msg.get("content") or ""
        pieces.append(f"{role}: {content}")
    return "\n".join(pieces)


def _extract_error_body(error: HTTPError) -> str:
    try:
        return error.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _http_error_message(error: HTTPError, *, suffix: str = "") -> str:
    status = getattr(error, "code", None)
    reason = getattr(error, "reason", "HTTP error")
    message = f"HTTP {status or ''} {reason} from Nox endpoint"
    if status == 401:
        message += ": unauthorized (set NOX_LLM_API_KEY or OPENAI_API_KEY?)"
    elif status == 404:
        message += ": endpoint not found (URL path invalid?)"
    if suffix:
        message = f"{message}\n{suffix}"
    return message


def _extract_sse_piece(data_str: str) -> Optional[str]:
    try:
        event = json.loads(data_str)
    except Exception:
        if not data_str.strip().startswith("{"):
            return data_str
        return None

    choice = (event.get("choices") or [{}])[0]
    delta = choice.get("delta") or {}
    piece = delta.get("content")
    if piece is None:
        piece = (choice.get("message") or {}).get("content")
    if piece is None:
        piece = choice.get("text")
    return piece
