from __future__ import annotations

import json
from pathlib import Path

from noxl import list_sessions, load_session_messages


def _write_json_session(dirpath: Path, stem: str, turns: int = 2) -> Path:
    records = []
    for idx in range(1, turns + 1):
        records.append(
            {
                "messages": [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": f"u{idx}"},
                    {"role": "assistant", "content": f"a{idx}"},
                ],
                "meta": {"turn": idx},
            }
        )
    path = dirpath / f"{stem}.json"
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_list_sessions_includes_json(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    day_dir = root / "2025-01-01"
    day_dir.mkdir(parents=True)

    path = _write_json_session(day_dir, "session-20250101-010101", turns=3)

    items = list_sessions(root)
    assert len(items) == 1
    info = items[0]
    assert info["id"] == path.stem
    assert info["turns"] == 3

    messages = load_session_messages(path)
    # Expect 1 system + 3 user + 3 assistant entries => 7 total messages
    assert len(messages) == 7
    assert messages[1]["content"] == "u1"
    assert messages[2]["content"] == "a1"
