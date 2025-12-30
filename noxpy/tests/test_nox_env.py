"""Coverage for the secure environment loader."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import nox_env


def test_get_env_prefers_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret_file = tmp_path / "secrets.env"
    secret_file.write_text("API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("NOCTICS_SECRETS_FILE", str(secret_file))
    monkeypatch.setenv("API_KEY", "from-env")
    # Reset cache to ensure reload
    monkeypatch.setattr(nox_env, "_SECRETS_CACHE", None, raising=False)

    assert nox_env.get_env("API_KEY") == "from-env"


def test_get_env_reads_secrets_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret_file = tmp_path / "secrets.env"
    secret_file.write_text(
        """
        # comment
        API_KEY=from-file

        """
        ,
        encoding="utf-8",
    )
    monkeypatch.setenv("NOCTICS_SECRETS_FILE", str(secret_file))
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setattr(nox_env, "_SECRETS_CACHE", None, raising=False)

    assert nox_env.get_env("API_KEY") == "from-file"


def test_get_env_reads_secrets_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "API_TOKEN").write_text("dir-value\n", encoding="utf-8")
    monkeypatch.setenv("NOCTICS_SECRETS_DIR", str(secrets_dir))
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setattr(nox_env, "_SECRETS_CACHE", None, raising=False)

    assert nox_env.get_env("API_TOKEN") == "dir-value"


def test_require_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nox_env, "_SECRETS_CACHE", {}, raising=False)
    monkeypatch.delenv("MISSING_KEY", raising=False)
    with pytest.raises(RuntimeError):
        nox_env.require_env("MISSING_KEY")
