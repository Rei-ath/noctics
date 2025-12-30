"""HTTP runtime wrapper around ChatClient for mobile or remote callers."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = PACKAGE_ROOT.parent
for candidate in (PROJECT_ROOT, PACKAGE_ROOT):
    if candidate.is_dir():
        path_str = str(candidate)
        if path_str not in sys.path:
            sys.path.append(path_str)

from central.core import ChatClient

LOGGER = logging.getLogger("noctics.runtime")


@dataclass(slots=True)
class RuntimeConfig:
    """Configuration for the lightweight runtime server."""

    host: str = "127.0.0.1"
    port: int = 11437
    default_url: Optional[str] = None
    default_model: Optional[str] = None
    allow_origin: Optional[str] = "*"
    strip_reasoning: bool = True
    log_sessions: bool = False


class ChatRuntimeServer:
    """Expose the ChatClient over a very small HTTP API."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self._httpd: Optional[ThreadingHTTPServer] = None

    # ------------------
    # HTTP server wiring
    # ------------------
    def serve_forever(self) -> None:
        """Start the HTTP server and block until interrupted."""

        if self._httpd is not None:
            raise RuntimeError("Runtime server is already running.")

        handler = self._build_handler()
        self._httpd = ThreadingHTTPServer((self.config.host, self.config.port), handler)
        self._httpd.daemon_threads = True  # type: ignore[attr-defined]
        self._httpd.runtime = self  # type: ignore[attr-defined]
        self._httpd.runtime_config = self.config  # type: ignore[attr-defined]

        LOGGER.info(
            "Nox runtime listening on http://%s:%s/api/chat (model default=%s)",
            self.config.host,
            self.config.port,
            self.config.default_model or os.getenv("NOX_LLM_MODEL") or "<env-required>",
        )
        try:
            self._httpd.serve_forever()
        except KeyboardInterrupt:
            LOGGER.info("Shutting down runtime server (interrupt received).")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        if self._httpd is None:
            return
        try:
            self._httpd.shutdown()
        finally:
            self._httpd.server_close()
            self._httpd = None

    # -------------
    # Core routing
    # -------------
    def handle_chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process a /api/chat request and return the response payload."""

        messages = self._normalize_messages(payload.get("messages"))
        if not messages:
            raise ValueError("Payload must include at least one message.")

        last = messages[-1]
        if last.get("role") != "user":
            raise ValueError("Last message in the list must be a user turn.")

        history = messages[:-1]
        prompt = str(last.get("content") or "")

        if payload.get("stream"):
            raise ValueError("Streaming mode is not supported by this runtime.")

        temperature = self._coerce_float(payload.get("temperature"), 0.7, "temperature")
        max_tokens = self._coerce_int(payload.get("max_tokens"), -1, "max_tokens")
        strip_reasoning = payload.get("strip_reasoning")
        if strip_reasoning is None:
            strip_reasoning = self.config.strip_reasoning

        client = ChatClient(
            url=payload.get("url") or self.config.default_url,
            model=payload.get("model") or self.config.default_model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            sanitize=bool(payload.get("sanitize", False)),
            messages=history,
            strip_reasoning=bool(strip_reasoning),
            enable_logging=bool(self.config.log_sessions),
            memory_user=payload.get("memory_user"),
            memory_user_display=payload.get("memory_user_display"),
        )

        reply = client.one_turn(prompt)
        target = client.describe_target()
        meta = {
            "target": target,
        }
        if client.instrument_warning:
            meta["instrument_warning"] = client.instrument_warning
        log_path = client.log_path()
        if log_path:
            meta["session_log"] = str(log_path)

        return {
            "message": {
                "role": "assistant",
                "content": reply or "",
            },
            "meta": meta,
        }

    # -----------------
    # Helper utilities
    # -----------------
    @staticmethod
    def _normalize_messages(raw: Any) -> List[Dict[str, str]]:
        if not raw:
            return []
        normalized: List[Dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            if role not in {"user", "assistant", "system"}:
                continue
            content = item.get("content")
            if isinstance(content, list):
                parts: List[str] = []
                for chunk in content:
                    if isinstance(chunk, dict):
                        value = chunk.get("text") or chunk.get("value")
                        if isinstance(value, str):
                            parts.append(value)
                    elif isinstance(chunk, str):
                        parts.append(chunk)
                content = "\n".join(parts)
            normalized.append(
                {
                    "role": str(role),
                    "content": "" if content is None else str(content),
                }
            )
        return normalized

    @staticmethod
    def _coerce_float(value: Any, default: float, field: str) -> float:
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError(f"{field} must be a float") from exc

    @staticmethod
    def _coerce_int(value: Any, default: int, field: str) -> int:
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError(f"{field} must be an integer") from exc

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class ChatRequestHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover - passthrough logging
                LOGGER.info("%s - %s", self.address_string(), fmt % args)

            # OPTIONS preflight for CORS
            def do_OPTIONS(self) -> None:  # noqa: N802 (http verb)
                self.send_response(HTTPStatus.NO_CONTENT)
                self._cors_headers()
                self.end_headers()

            def do_POST(self) -> None:  # noqa: N802 (http verb)
                if self.path.rstrip("/") != "/api/chat":
                    self._json_response({"error": "Not Found"}, HTTPStatus.NOT_FOUND)
                    return
                raw_body = self._read_body()
                if raw_body is None:
                    self._json_response({"error": "Request body required"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    payload = json.loads(raw_body.decode("utf-8"))
                except json.JSONDecodeError:
                    self._json_response({"error": "Invalid JSON body"}, HTTPStatus.BAD_REQUEST)
                    return
                if not isinstance(payload, dict):
                    self._json_response({"error": "JSON payload must be an object"}, HTTPStatus.BAD_REQUEST)
                    return

                try:
                    response = server.handle_chat(payload)
                except ValueError as exc:
                    self._json_response({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                except Exception as exc:  # pragma: no cover - runtime guard
                    LOGGER.exception("Runtime failure handling request: %s", exc)
                    self._json_response({"error": "Runtime failure"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                self._json_response(response, HTTPStatus.OK)

            # -------------
            # I/O helpers
            # -------------
            def _cors_headers(self) -> None:
                allow_origin = server.config.allow_origin
                if allow_origin is None:
                    return
                self.send_header("Access-Control-Allow-Origin", allow_origin)
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

            def _json_response(self, payload: Dict[str, Any], status: HTTPStatus) -> None:
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self._cors_headers()
                self.end_headers()
                self.wfile.write(encoded)

            def _read_body(self) -> Optional[bytes]:
                length_header = self.headers.get("Content-Length")
                if not length_header:
                    return None
                try:
                    length = int(length_header)
                except ValueError:
                    return None
                return self.rfile.read(length)

        return ChatRequestHandler


# -----------------
# CLI entrypoints
# -----------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nox-runtime",
        description="Expose the Nox ChatClient through a simple HTTP endpoint for mobile clients.",
    )
    parser.add_argument("--host", default=os.getenv("NOX_RUNTIME_HOST", "127.0.0.1"), help="Host to bind (default: 127.0.0.1).")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("NOX_RUNTIME_PORT", "11437")),
        help="Port to bind (default: 11437).",
    )
    parser.add_argument(
        "--default-url",
        default=os.getenv("NOX_RUNTIME_URL", os.getenv("NOX_LLM_URL")),
        help="Fallback NOX_LLM_URL for the ChatClient (defaults to NOX_LLM_URL env).",
    )
    parser.add_argument(
        "--default-model",
        default=os.getenv("NOX_RUNTIME_MODEL", os.getenv("NOX_LLM_MODEL")),
        help="Fallback NOX_LLM_MODEL for the ChatClient (defaults to NOX_LLM_MODEL env).",
    )
    parser.add_argument(
        "--allow-origin",
        default=os.getenv("NOX_RUNTIME_ALLOW_ORIGIN", "*"),
        help="CORS Access-Control-Allow-Origin header (default: '*').",
    )
    parser.add_argument(
        "--log-sessions",
        action="store_true",
        help="Enable on-disk session logging. Disabled by default for stateless HTTP calls.",
    )
    parser.add_argument(
        "--strip-reasoning",
        dest="strip_reasoning",
        action="store_true",
        default=True,
        help="Strip hidden reasoning blocks before returning replies (default).",
    )
    parser.add_argument(
        "--no-strip-reasoning",
        dest="strip_reasoning",
        action="store_false",
        help="Return the model output verbatim (keeps hidden reasoning).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging for the runtime server.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )

    config = RuntimeConfig(
        host=args.host,
        port=args.port,
        default_url=args.default_url,
        default_model=args.default_model,
        allow_origin=args.allow_origin,
        strip_reasoning=bool(args.strip_reasoning),
        log_sessions=bool(args.log_sessions),
    )

    server = ChatRuntimeServer(config)
    server.serve_forever()
    return 0
