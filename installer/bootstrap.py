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
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse
from urllib.request import urlopen
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
CORE_ROOT = REPO_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from noctics_cli.paths import bin_dir, install_home  # noqa: E402
from noctics_cli.setup import ensure_global_config_home  # noqa: E402
from noctics_cli.metrics import record_install_event  # noqa: E402

try:  # pragma: no cover - optional dependency when core isn't bundled with bootstrapper
    from interfaces.paths import resolve_memory_root as _core_resolve_memory_root  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover
    _core_resolve_memory_root = None  # type: ignore

DEFAULT_MANIFEST_URL = "https://example.com/noctics/installer_manifest.json"
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


def extract_archive(archive: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    suffix = archive.suffix.lower()
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
            zf.extractall(temp_dir)
    else:
        with tarfile.open(archive, "r:*") as tf:
            tf.extractall(temp_dir)

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
    for path in root.rglob("noctics-core"):
        if path.is_file():
            return path
    for path in root.rglob("noctics-core.exe"):
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


def run(manifest_ref: str, slug_override: Optional[str] = None, force: bool = False) -> Tuple[Path, Path]:
    slug = slug_override or detect_platform_slug()
    manifest = read_manifest(manifest_ref)
    entry = manifest.get(slug)
    if not entry:
        available = ", ".join(sorted(manifest.keys()))
        raise RuntimeError(f"No artifact for '{slug}'. Available: {available}")

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
        run(args.manifest, slug_override=args.slug, force=args.force)
    except Exception as exc:
        print(f"Installer failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
