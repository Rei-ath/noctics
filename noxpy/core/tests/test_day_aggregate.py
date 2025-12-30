from __future__ import annotations

import json
from pathlib import Path

from central.core import ChatClient


def test_append_session_to_day_log_dedup(tmp_path: Path) -> None:
    client = ChatClient(enable_logging=True)
    assert client.logger is not None
    client.logger.dirpath = tmp_path / "sessions"
    client.logger.start()

    client.record_turn("hi", "hello")
    path = client.log_path()
    assert path is not None

    day_log = client.append_session_to_day_log()
    assert day_log is not None

    # Append again; should replace existing entry instead of duplicating
    client.append_session_to_day_log()

    data = json.loads(day_log.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["id"] == path.stem
