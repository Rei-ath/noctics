"""Adaptive installer bootstrapper for Noctics.

This script detects the host platform, downloads the matching release archive,
verifies checksums, extracts the payload into the per-user install root, and
installs a shim on PATH. It relies on the manifest produced during release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse
from urllib.request import urlopen
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO_ROOT / "core"
for candidate in (REPO_ROOT, CORE_ROOT):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:  # pragma: no cover - optional when bootstrap is fetched standalone
    from noctics_cli.paths import bin_dir, install_home, config_home  # type: ignore  # noqa: E402
    from noctics_cli.setup import ensure_global_config_home  # type: ignore  # noqa: E402
    from noctics_cli.metrics import record_install_event  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover
    def _env_path(name: str) -> Optional[Path]:
        value = os.getenv(name)
        if not value:
            return None
        return Path(value).expanduser()

    def config_home() -> Path:
        override = _env_path("NOCTICS_CONFIG_HOME")
        if override:
            return override

        home = Path.home()
        if sys.platform == "win32":
            base = Path(os.getenv("APPDATA", home / "AppData" / "Roaming"))
            return base / "Noctics"
        if sys.platform == "darwin":
            base = home / "Library" / "Application Support"
            return base / "Noctics"
        base = Path(os.getenv("XDG_CONFIG_HOME", home / ".config"))
        return base / "noctics"

    def install_home() -> Path:
        override = _env_path("NOCTICS_INSTALL_HOME")
        if override:
            return override

        home = Path.home()
        if sys.platform == "win32":
            base = Path(os.getenv("LOCALAPPDATA", home / "AppData" / "Local"))
            return base / "Noctics"
        if sys.platform == "darwin":
            base = home / "Library" / "Application Support"
            return base / "Noctics" / "Runtime"
        base = Path(os.getenv("XDG_DATA_HOME", home / ".local" / "share"))
        return base / "noctics"

    def bin_dir() -> Path:
        override = _env_path("NOCTICS_BIN_DIR")
        if override:
            return override

        home = Path.home()
        if sys.platform == "win32":
            base = Path(os.getenv("LOCALAPPDATA", home / "AppData" / "Local"))
            return base / "Noctics" / "bin"
        return home / ".local" / "bin"

    def ensure_global_config_home() -> tuple[Path, Path, Path]:
        root = config_home()
        root.mkdir(parents=True, exist_ok=True)
        config_path = root / "central.json"
        secrets_path = root / "secrets.env"
        os.environ.setdefault("NOCTICS_CONFIG_HOME", str(root))
        os.environ.setdefault("NOX_CONFIG", str(config_path))
        os.environ.setdefault("NOCTICS_SECRETS_FILE", str(secrets_path))
        return root, config_path, secrets_path

    def _load_metrics(metrics_path: Path) -> Dict[str, Any]:
        if not metrics_path.exists():
            return {}
        try:
            raw = metrics_path.read_text(encoding="utf-8")
        except OSError:
            return {}
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _dump_metrics(metrics_path: Path, data: Dict[str, Any]) -> None:
        tmp_path = metrics_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_path.replace(metrics_path)
        except OSError:
            tmp_path.unlink(missing_ok=True)

    def record_install_event(
        memory_root: Path,
        *,
        version: str,
        slug: str,
        build: Optional[str] = None,
        now: datetime | None = None,
    ) -> None:
        metrics_dir = memory_root / "telemetry"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        metrics_path = metrics_dir / "metrics.json"

        data = _load_metrics(metrics_path)
        installs = data.get("installs")
        if not isinstance(installs, dict):
            installs = {}

        total = int(installs.get("total") or 0) + 1
        per_version = installs.get("per_version")
        if not isinstance(per_version, dict):
            per_version = {}
        version_key = str(version)
        per_version[version_key] = int(per_version.get(version_key) or 0) + 1

        per_slug = installs.get("per_slug")
        if not isinstance(per_slug, dict):
            per_slug = {}
        slug_key = str(slug)
        per_slug[slug_key] = int(per_slug.get(slug_key) or 0) + 1

        now = now or datetime.now(timezone.utc)
        event: Dict[str, str] = {
            "time": now.isoformat(),
            "version": version_key,
            "slug": slug_key,
        }
        if build:
            event["build"] = build

        history = installs.get("history")
        if isinstance(history, list):
            history = history + [event]
            history = history[-200:]
        else:
            history = [event]

        installs.update(
            {
                "total": total,
                "last": event,
                "per_version": per_version,
                "per_slug": per_slug,
                "history": history,
            }
        )

        data["installs"] = installs
        _dump_metrics(metrics_path, data)

try:  # pragma: no cover - optional dependency when core isn't bundled with bootstrapper
    from interfaces.paths import resolve_memory_root as _core_resolve_memory_root  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover
    _core_resolve_memory_root = None  # type: ignore

DEFAULT_MANIFEST_URL = "https://github.com/noctics/noctics/releases/latest/download/installer_manifest.json"
ARCHIVE_TYPES = {".zip": "zip", ".tar.gz": "tar", ".tgz": "tar", ".tar": "tar"}


def detect_platform_slug() -> str:
    platform = sys.platform
    machine = (os.uname().machine if hasattr(os, "uname") else platform_machine()).lower()  # type: ignore
    arch = "x86_64"
    if machine in {"x86_64", "amd64"}:
        arch = "x86_64"
    elif machine in {"aarch64", "arm64"}:
        arch = "arm64"
    elif machine.startswith("arm"):
        arch = "armhf"
    elif machine in {"i386", "i686"}:
        arch = "x86"

    if platform.startswith("linux"):
        return f"linux-{arch}"
    if platform == "darwin":
        return f"macos-{arch}"
    if platform in {"win32", "cygwin"}:
        return f"windows-{arch}"
    raise RuntimeError(f"Unsupported platform: {platform}/{machine}")


def platform_machine() -> str:
    import platform

    return platform.machine()


def read_manifest(manifest_ref: str) -> Dict[str, Any]:
    parsed = urlparse(manifest_ref)
    if parsed.scheme in {"", "file"}:
        path = Path(parsed.path or manifest_ref).expanduser()
        return json.loads(path.read_text(encoding="utf-8"))
    with urlopen(manifest_ref) as resp:  # nosec - controlled release URL
        data = resp.read().decode(resp.headers.get_content_charset() or "utf-8")
    return json.loads(data)


def download_file(url: str, dest: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme in {"", "file"}:
        src = Path(parsed.path or url).expanduser()
        shutil.copy(src, dest)
        return
    with urlopen(url) as resp:  # nosec - release download
        with dest.open("wb") as fh:
            shutil.copyfileobj(resp, fh)


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):  # type: ignore[arg-type]
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(path: Path, expected: Optional[str]) -> None:
    if not expected:
        return
    actual = compute_sha256(path)
    if actual.lower() != expected.lower():
        raise RuntimeError(f"Checksum mismatch for {path.name}: expected {expected}, got {actual}")


def _looks_like_windows_absolute(name: str) -> bool:
    if not name:
        return False
    if name.startswith(("//", "\\\\")):
        return True
    return len(name) >= 2 and name[1] == ":" and name[0].isalpha()


def _safe_archive_relative_path(name: str) -> Path:
    """Return a safe relative path for an archive entry or raise."""

    normalized = (name or "").replace("\\", "/")
    if not normalized:
        return Path(".")
    if normalized.startswith("/"):
        raise RuntimeError(f"Archive entry has an absolute path: {name}")
    if _looks_like_windows_absolute(normalized):
        raise RuntimeError(f"Archive entry has an absolute Windows path: {name}")
    candidate = Path(normalized)
    if candidate.is_absolute():
        raise RuntimeError(f"Archive entry has an absolute path: {name}")
    if ".." in candidate.parts:
        raise RuntimeError(f"Archive entry attempts path traversal: {name}")
    return candidate


def _ensure_within_directory(root: Path, path: Path) -> None:
    root_resolved = root.resolve()
    target_resolved = path.resolve()
    if root_resolved == target_resolved:
        return
    if root_resolved not in target_resolved.parents:
        raise RuntimeError(f"Archive entry escapes extraction directory: {path}")


def _apply_mode(path: Path, mode: int) -> None:
    if mode <= 0:
        return
    try:
        os.chmod(path, mode)
    except Exception:
        pass


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for info in zf.infolist():
        rel = _safe_archive_relative_path(info.filename)
        if rel == Path("."):
            continue
        target = dest / rel
        _ensure_within_directory(dest, target)

        mode = (info.external_attr >> 16) & 0o7777
        is_symlink = stat.S_ISLNK(info.external_attr >> 16)
        if is_symlink:
            raise RuntimeError(f"Refusing to extract symlink from zip archive: {info.filename}")

        if info.is_dir() or info.filename.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            _apply_mode(target, mode)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        _apply_mode(target, mode)


def _safe_extract_tar(tf: tarfile.TarFile, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for member in tf.getmembers():
        rel = _safe_archive_relative_path(member.name)
        if rel == Path("."):
            continue
        target = dest / rel
        _ensure_within_directory(dest, target)

        if member.islnk() or member.issym():
            raise RuntimeError(f"Refusing to extract link from tar archive: {member.name}")
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            _apply_mode(target, member.mode)
            continue
        if member.isfile():
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = tf.extractfile(member)
            if extracted is None:
                continue
            with extracted, target.open("wb") as handle:
                shutil.copyfileobj(extracted, handle)
            _apply_mode(target, member.mode)
            continue
        raise RuntimeError(f"Unsupported tar entry type: {member.name}")


def extract_archive(archive: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    archive_type = None
    for ext, kind in ARCHIVE_TYPES.items():
        if str(archive).lower().endswith(ext):
            archive_type = kind
            break
    if archive_type is None:
        raise RuntimeError(f"Unsupported archive type: {archive}")

    temp_dir = dest / "_tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    if archive_type == "zip":
        with zipfile.ZipFile(archive) as zf:
            _safe_extract_zip(zf, temp_dir)
    else:
        with tarfile.open(archive, "r:*") as tf:
            _safe_extract_tar(tf, temp_dir)

    contents = list(temp_dir.iterdir())
    root = contents[0] if len(contents) == 1 and contents[0].is_dir() else temp_dir
    return root


def find_binary(root: Path) -> Path:
    candidates = [
        root / "noctics-core",
        root / "noctics-core.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    for suffix in ("noctics-core", "noctics-core.exe"):
        for path in root.rglob(suffix):
            if path.is_file():
                return path
    raise RuntimeError("Unable to locate noctics-core binary in archive")


def install_payload(root: Path, install_root: Path) -> Path:
    runtime_dir = install_root / "runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    runtime_dir.parent.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    for item in root.iterdir():
        destination = runtime_dir / item.name
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        shutil.move(str(item), destination)
    return runtime_dir


def create_shim(binary: Path) -> Path:
    target_bin = bin_dir()
    target_bin.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        shim = target_bin / "noctics.cmd"
        content = f"@echo off\n\"{binary}\" %*\n"
        shim.write_text(content, encoding="utf-8")
    else:
        shim = target_bin / "noctics"
        content = f"#!/usr/bin/env bash\n\"{binary}\" \"$@\"\n"
        shim.write_text(content, encoding="utf-8")
        shim.chmod(0o755)
    return shim


def _resolve_memory_home() -> Path:
    if _core_resolve_memory_root is not None:
        try:
            return _core_resolve_memory_root()
        except Exception:
            pass

    override = os.getenv("NOCTICS_MEMORY_HOME")
    if override:
        target = Path(override).expanduser()
    else:
        data_root = os.getenv("NOCTICS_DATA_ROOT")
        if data_root:
            base = Path(data_root).expanduser()
        else:
            xdg_data = os.getenv("XDG_DATA_HOME")
            if xdg_data:
                base = Path(xdg_data).expanduser()
            else:
                base = Path.home() / ".local" / "share"
        target = base / "noctics" / "memory"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _resolve_manifest_entry(
    manifest: Dict[str, Any],
    slug: str,
) -> Dict[str, Any]:
    raw_entry = manifest.get(slug)
    if raw_entry is None:
        available = ", ".join(sorted(manifest.keys()))
        raise RuntimeError(f"No artifact for '{slug}'. Available: {available}")
    if not isinstance(raw_entry, dict):
        raise RuntimeError(f"Manifest entry for '{slug}' has unexpected format")
    return raw_entry


def run(
    manifest_ref: str,
    slug_override: Optional[str] = None,
    *,
    force: bool = False,
) -> Tuple[Path, Path]:
    slug = slug_override or detect_platform_slug()
    manifest = read_manifest(manifest_ref)
    entry = _resolve_manifest_entry(manifest, slug)

    url = entry.get("url")
    if not url:
        raise RuntimeError(f"Manifest entry for '{slug}' missing 'url'")
    sha256 = entry.get("sha256")
    version = str(entry.get("version") or "unknown")
    build_label = entry.get("build")
    build_label = str(build_label) if build_label else None
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / Path(urlparse(url).path).name
        download_file(url, tmp_path)
        verify_checksum(tmp_path, sha256)
        extract_root = extract_archive(tmp_path, Path(tmp))

        install_root_dir = install_home()
        if force and install_root_dir.exists():
            shutil.rmtree(install_root_dir)
        install_root_dir.mkdir(parents=True, exist_ok=True)

        runtime_dir = install_payload(extract_root, install_root_dir)
        binary = find_binary(runtime_dir)
        shim = create_shim(binary)

    ensure_global_config_home()
    try:
        memory_root = _resolve_memory_home()
        record_install_event(memory_root, version=version, slug=slug, build=build_label)
    except Exception:
        pass

    print(f"Installed Noctics runtime to {install_root_dir}")
    print(f"Launcher shim created at {shim}")
    print("Run 'noctics --setup' to configure instruments if you haven't already.")
    return install_root_dir, shim


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Install the Noctics runtime")
    parser.add_argument(
        "--manifest",
        default=os.getenv("NOCTICS_INSTALLER_MANIFEST", DEFAULT_MANIFEST_URL),
        help="URL or file path to installer manifest",
    )
    parser.add_argument(
        "--slug",
        default=None,
        help="Override detected platform slug (e.g. linux-x86_64)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Remove existing installation before installing",
    )
    args = parser.parse_args(argv)
    try:
        run(
            args.manifest,
            slug_override=args.slug,
            force=args.force,
        )
    except Exception as exc:
        print(f"Installer failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
