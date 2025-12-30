from __future__ import annotations

from pathlib import Path

from central.core import ChatClient


def test_empty_session_deleted(tmp_path: Path) -> None:
    client = ChatClient(enable_logging=True)
    assert client.logger is not None
    client.logger.dirpath = tmp_path
    client.logger.start()

    log_path = client.log_path()
    assert log_path is not None and log_path.exists()

    removed = client.maybe_delete_empty_session()
    assert removed
    assert not log_path.exists()
    meta = log_path.with_name(log_path.stem + ".meta.json")
    assert not meta.exists()
