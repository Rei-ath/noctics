#!/usr/bin/env python3
"""Migrate OpenAI ChatGPT exports into Noctics-compatible session logs."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence

DEFAULT_EXPORT = Path("data/openai_chat_exports/conversations.json")
DEFAULT_OUTPUT_ROOT = Path("memory/imported/openai")
DEFAULT_MAX_TURNS = 30

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def unix_to_iso(ts: Optional[float]) -> Optional[str]:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def safe_title(title: Optional[str]) -> str:
    if title:
        return title.strip()
    return "Imported OpenAI Conversation"


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def chunk_messages(messages: Sequence["Message"], include_system: bool = True) -> Iterator[List["Message"]]:
    """Yield batches of messages representing one logical turn."""

    window: List[Message] = []
    for message in messages:
        if message.role == "system" and not include_system:
            continue
        if message.is_empty():
            continue
        window.append(message)
        if message.role in {"assistant", "tool"}:
            yield window
            window = []
    if window:
        yield window


# ---------------------------------------------------------------------------
# Data model wrappers
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Message:
    role: str
    content: str
    created: Optional[float] = None
    raw: Optional[dict] = None

    def is_empty(self) -> bool:
        return not self.content or not self.content.strip()


@dataclasses.dataclass
class Conversation:
    raw: Dict

    def messages(self) -> List[Message]:
        mapping = self.raw.get("mapping", {})
        node_id = self.raw.get("current_node")
        path: List[dict] = []
        while node_id:
            node = mapping.get(node_id)
            if not node:
                break
            path.append(node)
            node_id = node.get("parent")
        path.reverse()

        messages: List[Message] = []
        for node in path:
            message = node.get("message")
            if not message:
                continue
            author = (message.get("author") or {}).get("role", "unknown")
            content = message.get("content") or {}
            parts = content.get("parts") or []
            text_parts = [part for part in parts if isinstance(part, str)]
            text = "\n".join(text_parts)
            messages.append(
                Message(
                    role=author,
                    content=text,
                    created=message.get("create_time"),
                    raw=message,
                )
            )
        return messages

    @property
    def title(self) -> str:
        return safe_title(self.raw.get("title"))

    @property
    def created(self) -> Optional[str]:
        return unix_to_iso(self.raw.get("create_time"))

    @property
    def updated(self) -> Optional[str]:
        return unix_to_iso(self.raw.get("update_time"))

    @property
    def model(self) -> Optional[str]:
        return self.raw.get("default_model_slug")

    @property
    def conversation_id(self) -> str:
        return self.raw.get("id") or self.raw.get("conversation_id")

    def date_folder(self) -> str:
        if self.updated:
            return self.updated.split("T", 1)[0]
        if self.created:
            return self.created.split("T", 1)[0]
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclasses.dataclass
class TurnRecord:
    messages: List[Message]
    turn_number: int
    model: Optional[str]
    timestamp: Optional[str]

    def to_json_line(self, file_name: str, display_name: str, source_tag: str) -> str:
        payload = {
            "messages": [
                {"role": msg.role, "content": msg.content}
                for msg in self.messages
            ],
            "meta": {
                "model": self.model,
                "sanitized": False,
                "turn": self.turn_number,
                "ts": self.timestamp,
                "file_name": file_name,
                "display_name": display_name,
                "source": source_tag,
            },
        }
        return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Migration pipeline
# ---------------------------------------------------------------------------

class MigrationContext:
    def __init__(self, export_path: Path, output_root: Path) -> None:
        self.export_path = export_path
        self.output_root = output_root

    def load_conversations(self) -> List[Conversation]:
        with self.export_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return [Conversation(conv) for conv in raw]

    def destination_for(self, conversation: Conversation) -> Path:
        date_folder = conversation.date_folder()
        session_id = self.build_session_id(conversation)
        return self.output_root / date_folder / session_id

    @staticmethod
    def build_session_id(conversation: Conversation) -> str:
        base_time = conversation.created or conversation.updated
        if base_time:
            base_compact = base_time.replace("-", "").replace(":", "").replace("T", "")[:15]
        else:
            base_compact = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        conv_id = conversation.conversation_id or "unknown"
        conv_suffix = conv_id.replace("-", "")[:12]
        return f"session-openai-{base_compact}-{conv_suffix}"


def generate_turns(conversation: Conversation, source_tag: str) -> List[TurnRecord]:
    messages = conversation.messages()
    if not messages:
        return []

    # capture system messages separately to prepend to each turn's first message if desired
    system_messages = [msg for msg in messages if msg.role == "system" and not msg.is_empty()]
    non_system = [msg for msg in messages if msg.role != "system"]

    turns: List[TurnRecord] = []
    turn_index = 0
    for chunk in chunk_messages(non_system, include_system=False):
        if not chunk:
            continue
        turn_index += 1
        timestamp = chunk[-1].created or conversation.raw.get("update_time") or conversation.raw.get("create_time")
        turns.append(
            TurnRecord(
                messages=chunk,
                turn_number=turn_index,
                model=conversation.model,
                timestamp=unix_to_iso(timestamp),
            )
        )

    # prepend system context to first turn if present and first message isn't system already
    if system_messages and turns:
        prefix_text = "\n\n".join(msg.content for msg in system_messages if msg.content)
        if prefix_text:
            first_turn_msgs = turns[0].messages
            first_turn_msgs.insert(0, Message(role="system", content=prefix_text))

    return turns


def write_session(
    conversation: Conversation,
    ctx: MigrationContext,
    *,
    dry_run: bool = False,
    max_turns: Optional[int] = DEFAULT_MAX_TURNS,
) -> Path:
    session_root = ctx.destination_for(conversation)
    jsonl_path = session_root.with_suffix(".jsonl")
    meta_path = session_root.with_suffix(".meta.json")

    file_name = jsonl_path.name
    display_name = conversation.title or "Imported OpenAI Conversation"
    source_tag = "openai-chat-export"

    turns = generate_turns(conversation, source_tag=source_tag)
    if not turns:
        raise RuntimeError(f"Conversation '{conversation.conversation_id}' has no turns to migrate.")

    total_turns = len(turns)
    full_turns = [
        TurnRecord(messages=turn.messages, turn_number=index + 1, model=turn.model, timestamp=turn.timestamp)
        for index, turn in enumerate(turns)
    ]

    trimmed_turns: List[TurnRecord]
    trimmed = False
    if max_turns and max_turns > 0 and total_turns > max_turns:
        trimmed = True
        slice_start = total_turns - max_turns
        trimmed_turns = [
            TurnRecord(messages=turn.messages, turn_number=index + 1, model=turn.model, timestamp=turn.timestamp)
            for index, turn in enumerate(turns[slice_start:])
        ]
    else:
        trimmed_turns = full_turns

    if dry_run:
        kept = len(trimmed_turns)
        suffix = " (trimmed)" if trimmed else ""
        print(f"[dry-run] Would write {kept} of {total_turns} turns to {jsonl_path}{suffix}")
        return jsonl_path

    ensure_directory(jsonl_path.parent)

    with jsonl_path.open("w", encoding="utf-8") as fh:
        for turn in trimmed_turns:
            fh.write(turn.to_json_line(file_name=file_name, display_name=display_name, source_tag=source_tag))
            fh.write("\n")

    full_history_path = None
    if trimmed:
        full_history_path = jsonl_path.with_suffix(".full.jsonl")
        with full_history_path.open("w", encoding="utf-8") as fh:
            for turn in full_turns:
                fh.write(turn.to_json_line(file_name=file_name, display_name=display_name, source_tag=source_tag))
                fh.write("\n")
    else:
        extra_path = jsonl_path.with_suffix(".full.jsonl")
        extra_path.unlink(missing_ok=True)

    metadata = {
        "id": jsonl_path.stem,
        "path": str(jsonl_path.resolve()),
        "model": conversation.model,
        "sanitized": False,
        "turns": len(trimmed_turns),
        "created": conversation.created,
        "updated": conversation.updated,
        "title": conversation.title,
        "custom": True,
        "file_name": file_name,
        "display_name": display_name,
        "source": source_tag,
        "conversation_id": conversation.conversation_id,
        "imported_total_turns": total_turns,
        "imported_trimmed_turns": len(trimmed_turns),
    }
    if full_history_path is not None:
        metadata["full_history_path"] = str(full_history_path.resolve())

    with meta_path.open("w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    return jsonl_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate OpenAI chat exports into Noctics format")
    parser.add_argument("--export", type=Path, default=DEFAULT_EXPORT, help="Path to conversations.json")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="Destination root directory")
    parser.add_argument("--index", type=int, help="Single conversation index to migrate")
    parser.add_argument("--id", dest="conv_id", help="Single conversation id to migrate")
    parser.add_argument("--all", action="store_true", help="Migrate every conversation in the export")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing files")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS, help="Trim to the last N turns per session (0 = keep all)")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    ctx = MigrationContext(args.export, args.output_root)

    if not args.export.exists():
        raise SystemExit(f"Export file not found: {args.export}")

    conversations = ctx.load_conversations()
    if not conversations:
        print("No conversations found in export.")
        return 0

    targets: Iterable[Conversation]
    if args.all:
        targets = conversations
    elif args.conv_id:
        targets = [conv for conv in conversations if conv.conversation_id == args.conv_id]
        if not targets:
            raise SystemExit(f"Conversation id not found: {args.conv_id}")
    elif args.index is not None:
        if args.index < 0 or args.index >= len(conversations):
            raise SystemExit(f"Index out of range (0-{len(conversations)-1})")
        targets = [conversations[args.index]]
    else:
        print("No conversations selected. Use --index, --id, or --all.")
        return 1

    total = 0
    for conv in targets:
        try:
            path = write_session(conv, ctx, dry_run=args.dry_run, max_turns=args.max_turns)
            if args.dry_run:
                continue
            print(f"Migrated '{conv.title}' -> {path}")
            total += 1
        except Exception as exc:  # pragma: no cover - defensive
            print(f"Failed to migrate conversation {conv.conversation_id}: {exc}", file=sys.stderr)
    if args.all and not args.dry_run:
        print(f"Completed migration of {total} conversations to {args.output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
