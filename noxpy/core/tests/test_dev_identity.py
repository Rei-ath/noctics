from __future__ import annotations

import json
from pathlib import Path

import pytest

from interfaces.dev_identity import DeveloperIdentity, resolve_developer_identity


def test_resolve_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOX_DEV_NAME", "Rei")
    monkeypatch.setenv("NOX_DEV_ID", "rei_main")
    ident = resolve_developer_identity(project_name="Noctics Test", users_root=tmp_path)
    assert isinstance(ident, DeveloperIdentity)
    assert ident.user_id == "rei_main"
    assert ident.display_name == "Rei"
    assert "Noctics Test" in ident.context_line()


def test_resolve_from_user_meta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    users_root = tmp_path / "users"
    dev_dir = users_root / "rei"
    dev_dir.mkdir(parents=True)
    meta_path = dev_dir / "user.json"
    meta_path.write_text(
        json.dumps({"id": "rei", "display_name": "Rei", "developer": True}),
        encoding="utf-8",
    )
    monkeypatch.delenv("NOX_DEV_NAME", raising=False)
    monkeypatch.setenv("NOCTICS_PROJECT_NAME", "Noctics")
    ident = resolve_developer_identity(users_root=users_root)
    assert ident.display_name == "Rei"
    assert ident.user_id == "rei"


def test_resolve_defaults_to_rei(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOX_DEV_NAME", raising=False)
    monkeypatch.delenv("NOCTICS_DEV_NAME", raising=False)
    monkeypatch.delenv("NOX_USER_NAME", raising=False)
    ident = resolve_developer_identity(project_name="Noctics", users_root=tmp_path)
    assert ident.display_name == "Rei"
    assert ident.user_id == "rei"
