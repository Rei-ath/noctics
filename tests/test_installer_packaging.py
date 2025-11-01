"""End-to-end coverage for installer packaging and bootstrap flow."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest

from installer import bootstrap
from noctics_cli.metrics import record_cli_run, record_install_event


def _load_packager_module() -> ModuleType:
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    module_path = scripts_dir / "package_installer_artifacts.py"
    spec = importlib.util.spec_from_file_location("package_installer_artifacts", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load package_installer_artifacts module for tests")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PACKAGER = _load_packager_module()


def _create_stub_payload(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    binary = dest / "noctics-core"
    binary.write_text("#!/usr/bin/env bash\necho stub\n", encoding="utf-8")
    binary.chmod(0o755)
    (dest / "licenses").mkdir(exist_ok=True)
    (dest / "licenses" / "THIRD_PARTY_LICENSES.md").write_text("stub", encoding="utf-8")


def test_package_runtime_updates_manifest(tmp_path: Path) -> None:
    dist_dir = tmp_path / "build" / "noctics-core"
    _create_stub_payload(dist_dir)

    manifest_path = tmp_path / "installer_manifest.json"
    archive = _PACKAGER.package_runtime(
        dist_dir,
        tmp_path,
        slug="linux-x86_64",
        os_name="linux",
        arch="x86_64",
        manifest=manifest_path,
        url_prefix="https://cdn.test/releases",
        version="0.1.39",
        build="build-123",
    )

    assert archive.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["linux-x86_64"]
    assert entry["version"] == "0.1.39"
    assert entry["build"] == "build-123"
    assert entry["url"].endswith(archive.name)
    assert entry["size"] == archive.stat().st_size

    readme = dist_dir / "README.txt"
    assert readme.exists()
    assert "0.1.39" in readme.read_text(encoding="utf-8")


def test_bootstrap_installs_and_records_telemetry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist_dir = tmp_path / "payload" / "noctics-core"
    _create_stub_payload(dist_dir)

    manifest_path = tmp_path / "manifest.json"
    archive = _PACKAGER.package_runtime(
        dist_dir,
        tmp_path,
        slug="linux-x86_64",
        os_name="linux",
        arch="x86_64",
        manifest=manifest_path,
        version="0.1.40",
        build="ci-999",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["linux-x86_64"]["url"] = archive.as_uri()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    install_home = tmp_path / "install"
    bin_dir = tmp_path / "bin"
    config_home = tmp_path / "config"
    memory_home = tmp_path / "memory"

    monkeypatch.setenv("NOCTICS_INSTALL_HOME", str(install_home))
    monkeypatch.setenv("NOCTICS_BIN_DIR", str(bin_dir))
    monkeypatch.setenv("NOCTICS_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("NOCTICS_MEMORY_HOME", str(memory_home))

    install_root, shim = bootstrap.run(str(manifest_path), slug_override="linux-x86_64", force=True)

    assert install_root == install_home
    assert shim.exists()
    assert (install_home / "runtime" / "noctics-core").exists()

    metrics_path = memory_home / "telemetry" / "metrics.json"
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    installs = payload["installs"]
    assert installs["total"] == 1
    assert installs["per_slug"]["linux-x86_64"] == 1
    assert installs["per_version"]["0.1.40"] == 1
    assert installs["last"]["build"] == "ci-999"


def test_record_cli_run_preserves_install_stats(tmp_path: Path) -> None:
    memory_root = tmp_path / "memory"
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    record_install_event(memory_root, version="0.2.0", slug="linux-arm64", build="build-1", now=now)
    record_cli_run(memory_root, "0.2.0", now=now)

    metrics_path = memory_root / "telemetry" / "metrics.json"
    data = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert data["installs"]["total"] == 1
    assert data["total_runs"] == 1
    assert data["installs"]["per_version"]["0.2.0"] == 1
