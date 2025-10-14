#!/usr/bin/env python3
"""Tiny TCP bridge that exposes ChatClient to the GPU demo UI."""

from __future__ import annotations

import asyncio
import json
import signal
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = ROOT / 'core'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from central.core import ChatClient  # type: ignore  # pylint: disable=wrong-import-position

DEFAULT_ADDR = "127.0.0.1"
DEFAULT_PORT = 4510


def load_system_prompt() -> str | None:
    for candidate in (
        ROOT / "memory" / "system_prompt.local.txt",
        ROOT / "memory" / "system_prompt.txt",
    ):
        try:
            if candidate.exists():
                return candidate.read_text(encoding="utf-8").strip()
        except Exception:
            continue
    return None


async def send_json(writer: asyncio.StreamWriter, payload: Dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False)
    writer.write((data + "\n").encode("utf-8"))
    try:
        await writer.drain()
    except ConnectionError:
        pass


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    loop = asyncio.get_running_loop()

    system_prompt = load_system_prompt()
    client = ChatClient(stream=True, sanitize=False)
    client.reset_messages(system=system_prompt)

    await send_json(writer, {"type": "hello", "message": "Noctics bridge ready"})
    if peer:
        await send_json(writer, {"type": "log", "text": f"Connected: {peer}"})

    while True:
        try:
            data = await reader.readline()
        except ConnectionError:
            break
        if not data:
            break
        try:
            message = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            await send_json(writer, {"type": "error", "message": f"invalid json: {exc}"})
            continue

        kind = message.get("type")
        if kind == "prompt":
            text = str(message.get("text") or "")
            if not text.strip():
                await send_json(writer, {"type": "error", "message": "empty prompt"})
                continue

            def on_delta(piece: str) -> None:
                if not piece:
                    return
                asyncio.run_coroutine_threadsafe(
                    send_json(writer, {"type": "delta", "text": piece}),
                    loop,
                )

            try:
                assistant = await asyncio.to_thread(client.one_turn, text, on_delta=on_delta)
            except Exception as exc:  # pragma: no cover - defensive
                await send_json(writer, {"type": "error", "message": str(exc)})
                continue
            await send_json(writer, {"type": "done", "text": assistant or ""})
        elif kind == "reset":
            client.reset_messages(system=system_prompt)
            await send_json(writer, {"type": "status", "message": "session reset"})
        else:
            await send_json(writer, {"type": "error", "message": f"unknown command: {kind}"})

    try:
        writer.close()
        await writer.wait_closed()
    except Exception:  # pragma: no cover - defensive
        pass


async def main() -> None:
    addr = DEFAULT_ADDR
    port = int(DEFAULT_PORT)
    server = await asyncio.start_server(handle_client, addr, port)
    sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    print(f"[bridge] listening on {sockets}")

    stop = asyncio.Future[None]()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(sig, stop.cancel)
        except NotImplementedError:
            pass

    try:
        await stop
    except asyncio.CancelledError:
        pass
    finally:
        server.close()
        await server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[bridge] stopped by user")
