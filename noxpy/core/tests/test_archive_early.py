from __future__ import annotations

import json
from pathlib import Path

from noxl import archive_early_sessions, list_sessions
from interfaces.session_logger import format_session_display_name


def _write_session(root: Path, day: str, stem: str, *, updated: str, title: str) -> Path:
    day_dir = root / day
    day_dir.mkdir(parents=True, exist_ok=True)
    log_path = day_dir / f"{stem}.json"
    record = {
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": stem},
            {"role": "assistant", "content": "ok"},
        ],
        "meta": {
            "model": "test",
            "sanitized": False,
            "turn": 1,
            "ts": updated,
        },
    }
    log_path.write_text(json.dumps([record], ensure_ascii=False, indent=2), encoding="utf-8")

    meta = {
        "id": stem,
        "path": str(log_path),
        "turns": 1,
        "model": "test",
        "sanitized": False,
        "title": title,
        "custom": True,
        "created": updated,
        "updated": updated,
        "file_name": log_path.name,
        "display_name": format_session_display_name(stem),
    }
    meta_path = log_path.with_name(f"{stem}.meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return log_path


def test_archive_early_sessions(tmp_path: Path) -> None:
    sessions_root = tmp_path / "memory" / "sessions"
    archive_root = tmp_path / "memory" / "early-archives"

    # Older sessions
    s1 = _write_session(
        sessions_root,
        "2024-09-17",
        "session-20240917-010101",
        updated="2024-09-17T01:01:01Z",
        title="First",
    )
    s2 = _write_session(
        sessions_root,
        "2024-09-18",
        "session-20240918-020202",
        updated="2024-09-18T02:02:02Z",
        title="Second",
    )
    # Latest session (should be excluded from archive)
    latest = _write_session(
        sessions_root,
        "2024-09-19",
        "session-20240919-030303",
        updated="2024-09-19T03:03:03Z",
        title="Latest",
    )

    out = archive_early_sessions(root=sessions_root, archive_root=archive_root)
    assert out is not None
    assert archive_root in out.parents
    assert out.exists()
    assert out.suffix == ".json"

    meta_path = out.with_name(out.stem + ".meta.json")
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    archive_info = meta.get("archive")
    assert archive_info is not None
    assert archive_info.get("latest_excluded_id") == "session-20240919-030303"
    assert archive_info.get("source_count") == 2

    # Latest session should remain
    assert latest.exists()

    # Original archived sessions should be removed
    assert not s1.exists()
    assert not s2.exists()
    assert not s1.with_name(s1.stem + ".meta.json").exists()
    assert not s2.with_name(s2.stem + ".meta.json").exists()

    # Sources noted in metadata
    sources = meta.get("sources")
    assert isinstance(sources, list)
    assert "session-20240917-010101" in sources
    assert "session-20240918-020202" in sources

    # Archive session should appear when listing archive root
    archive_list = list_sessions(archive_root)
    assert any(Path(item["path"]) == out for item in archive_list)
