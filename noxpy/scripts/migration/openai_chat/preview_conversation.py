#!/usr/bin/env python3
"""Preview conversations from an OpenAI ChatGPT export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_EXPORT = Path("data/openai_chat_exports/conversations.json")


class Conversation:
    def __init__(self, raw: Dict) -> None:
        self.raw = raw
        self.mapping: Dict[str, Dict] = raw["mapping"]
        self.current_node: Optional[str] = raw.get("current_node")

    def ordered_messages(self) -> List[Dict]:
        """Return messages from root to current node."""

        if not self.current_node:
            return []
        path = []
        node_id = self.current_node
        while node_id:
            node = self.mapping[node_id]
            path.append(node)
            node_id = node.get("parent")
        path.reverse()

        messages: List[Dict] = []
        for node in path:
            msg = node.get("message")
            if not msg:
                continue
            content = msg.get("content") or {}
            parts = content.get("parts") or []
            text = "\n".join(part for part in parts if isinstance(part, str))
            messages.append(
                {
                    "id": msg.get("id"),
                    "role": msg.get("author", {}).get("role", "unknown"),
                    "text": text,
                    "timestamp": msg.get("create_time"),
                }
            )
        return messages


def load_export(path: Path) -> List[Dict]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def choose_conversation(data: List[Dict], index: Optional[int], conv_id: Optional[str]) -> Dict:
    if index is not None:
        return data[index]
    if conv_id is not None:
        for conv in data:
            if conv.get("id") == conv_id or conv.get("conversation_id") == conv_id:
                return conv
        raise SystemExit(f"Conversation id not found: {conv_id}")
    return data[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect an OpenAI chat export")
    parser.add_argument(
        "--export",
        type=Path,
        default=DEFAULT_EXPORT,
        help="Path to conversations.json export",
    )
    parser.add_argument("--index", type=int, help="Conversation index to inspect (0-based)")
    parser.add_argument("--id", dest="conv_id", help="Conversation id to inspect")
    parser.add_argument("--max-chars", type=int, default=0, help="Trim message text to N chars")
    args = parser.parse_args()

    export_path = args.export
    if not export_path.exists():
        raise SystemExit(f"Export file not found: {export_path}")

    data = load_export(export_path)
    conv = choose_conversation(data, args.index, args.conv_id)
    transcript = Conversation(conv)

    messages = transcript.ordered_messages()
    title = conv.get("title", "(untitled)")
    conv_id = conv.get("id") or conv.get("conversation_id")
    print(f"Conversation Title: {title}")
    print(f"Conversation ID   : {conv_id}")
    print(f"Messages          : {len(messages)}")
    print("-" * 80)

    max_chars = args.max_chars or None
    for idx, message in enumerate(messages, start=1):
        role = message["role"].upper()
        text = message["text"] or ""
        if max_chars and len(text) > max_chars:
            text = text[: max_chars - 3] + "..."
        print(f"[{idx:03}] {role}")
        if text:
            print(text)
        else:
            print("(empty message)")
        print()


if __name__ == "__main__":
    main()
