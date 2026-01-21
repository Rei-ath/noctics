from __future__ import annotations

import json
from pathlib import Path

import pytest

from central.cli import RuntimeIdentity, resolve_runtime_identity


def test_resolve_runtime_identity_dev_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NOX_DEV_NAME", "DevUser")
    monkeypatch.setenv("NOX_DEV_ID", "dev_user")
    identity = resolve_runtime_identity(
        dev_mode=True,
        initial_label="You",
        interactive=True,
        users_root=tmp_path,
    )
    assert isinstance(identity, RuntimeIdentity)
    assert identity.user_id == "dev_user"
    assert identity.display_name == "DevUser"
    assert identity.context_line()
    assert not identity.created_user
    assert not list(tmp_path.iterdir())


def test_resolve_runtime_identity_interactive_user(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tmp_users = tmp_path / "users"
    monkeypatch.delenv("NOX_USER_NAME", raising=False)

    inputs = iter(["Charlie"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    identity = resolve_runtime_identity(
        dev_mode=False,
        initial_label="You",
        interactive=True,
        users_root=tmp_users,
    )
    assert identity.display_name == "Charlie"
    assert identity.user_id == "charlie"
    assert identity.created_user is True

    meta_path = tmp_users / "charlie" / "user.json"
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert data["id"] == "charlie"
    assert data["display_name"] == "Charlie"


def test_resolve_runtime_identity_noninteractive_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tmp_users = tmp_path / "users"
    monkeypatch.delenv("NOX_USER_NAME", raising=False)

    identity = resolve_runtime_identity(
        dev_mode=False,
        initial_label="",
        interactive=False,
        users_root=tmp_users,
    )
    assert identity.display_name == "Guest"
    assert identity.user_id == "guest"
    assert identity.created_user is True

    meta_path = tmp_users / "guest" / "user.json"
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert data["id"] == "guest"
    assert data["display_name"] == "Guest"
