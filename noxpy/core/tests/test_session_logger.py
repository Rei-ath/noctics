from __future__ import annotations

import json
from pathlib import Path

from interfaces.session_logger import SessionLogger, format_session_display_name


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def test_session_logger_creates_files_and_updates_meta(tmp_path: Path):
    logger = SessionLogger(model="test-model", sanitized=True, dirpath=tmp_path)
    logger.start()

    log_path = logger.log_path()
    meta_path = logger.meta_path()
    assert log_path is not None and log_path.exists()
    assert meta_path is not None and meta_path.exists()

    # Log one turn; verify meta updates
    logger.log_turn(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
    )
    meta1 = logger.get_meta()
    assert meta1.get("turns") == 1
    assert meta1.get("model") == "test-model"
    assert meta1.get("sanitized") is True
    assert meta1.get("file_name").endswith(".jsonl")
    session_id = meta1.get("id")
    assert session_id is not None
    assert meta1.get("display_name") == format_session_display_name(session_id)

    # Set a title and ensure it persists in meta
    logger.set_title("My Title", custom=True)
    meta2 = logger.get_meta()
    assert meta2.get("title") == "My Title"
    assert meta2.get("custom") is True
    assert meta2.get("display_name") == meta1.get("display_name")

    # Ensure JSONL record also carries the file/display metadata
    records = _read_jsonl(log_path)
    assert len(records) == 1
    meta_entry = records[0].get("meta", {})
    assert meta_entry.get("file_name") == log_path.name
    assert meta_entry.get("display_name") == meta1.get("display_name")


def test_session_logger_load_existing_appends(tmp_path: Path):
    base = tmp_path
    logger1 = SessionLogger(model="test", sanitized=False, dirpath=base)
    logger1.start()
    logger1.log_turn(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
        ]
    )
    log_path = logger1.log_path()
    assert log_path is not None

    logger2 = SessionLogger(model="test", sanitized=False, dirpath=base)
    logger2.load_existing(log_path)
    logger2.log_turn(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
        ]
    )

    records = _read_jsonl(log_path)
    assert len(records) == 2
    assert records[1]["messages"][1]["content"] == "u2"


def test_session_logger_writes_user_directory(tmp_path: Path) -> None:
    users_root = tmp_path / "users"
    logger = SessionLogger(
        model="test-user",
        sanitized=False,
        users_root=users_root,
        user_id="alice",
        user_display="Alice",
    )
    logger.start()
    log_path = logger.log_path()
    assert log_path is not None
    expected_root = users_root / "alice" / "sessions"
    assert expected_root in log_path.parents

    user_meta = users_root / "alice" / "user.json"
    assert user_meta.exists()
    meta_data = json.loads(user_meta.read_text(encoding="utf-8"))
    assert meta_data.get("id") == "alice"
    assert meta_data.get("display_name") == "Alice"
