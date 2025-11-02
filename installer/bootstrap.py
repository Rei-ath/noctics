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
import re
import shutil
import subprocess
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

DEFAULT_MANIFEST_URL = "https://github.com/noctics/noctics/releases/latest/download/installer_manifest.json"
VARIANT_ORDER = ["nano", "micro", "centi", "release"]
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
        root / "centi-noctics",
        root / "micro-noctics",
        root / "nano-noctics",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    for suffix in ("noctics-core", "noctics-core.exe", "centi-noctics", "micro-noctics", "nano-noctics"):
        for path in root.rglob(suffix):
            if path.is_file():
                return path
    for path in root.rglob("*-noctics"):
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


def _detect_vram_with_nvidia_smi() -> Optional[float]:
    command = [
        "nvidia-smi",
        "--query-gpu=memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        output = subprocess.check_output(
            command,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
    except Exception:
        return None
    values = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            values.append(float(line))
        except ValueError:
            continue
    if not values:
        return None
    # nvidia-smi returns MiB when nounits is enabled
    max_mb = max(values)
    return max_mb / 1024.0


def _detect_vram_with_system_profiler() -> Optional[float]:
    if sys.platform != "darwin":
        return None
    try:
        output = subprocess.check_output(
            ["system_profiler", "SPDisplaysDataType"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    matches = re.findall(r"VRAM.*?:\s*([\d.,]+)\s*(GB|MB)", output, flags=re.IGNORECASE)
    if not matches:
        return None
    best = 0.0
    for value, unit in matches:
        try:
            numeric = float(value.replace(",", ""))
        except ValueError:
            continue
        unit = unit.upper()
        if unit == "MB":
            numeric = numeric / 1024.0
        best = max(best, numeric)
    return best or None


def _detect_vram_from_env() -> Optional[float]:
    override = os.getenv("NOCTICS_INSTALLER_VRAM_GB") or os.getenv("NOCTICS_VRAM_GB")
    if not override:
        return None
    try:
        return float(override)
    except ValueError:
        return None


def detect_gpu_vram_gib() -> Optional[float]:
    """Best-effort detection of total GPU VRAM in GiB."""

    for detector in (
        _detect_vram_from_env,
        _detect_vram_with_nvidia_smi,
        _detect_vram_with_system_profiler,
    ):
        value = detector()
        if value and value > 0:
            return value
    return None


def _recommend_variant(
    available: Dict[str, Dict[str, Any]],
    *,
    vram_gib: Optional[float],
    default: Optional[str],
) -> str:
    # Fallback order ensures nano is always valid when present.
    ordered_variants = [name for name in VARIANT_ORDER if name in available]
    if not ordered_variants:
        ordered_variants = sorted(available.keys())

    thresholds = {
        "nano": 0.0,
        "micro": 8.0,
        "centi": 16.0,
        "release": 24.0,
    }

    if vram_gib is None:
        if default in available:
            return default  # prefer manifest-provided default when detection fails
        return ordered_variants[0]

    # Find the most capable variant that does not exceed detected VRAM.
    candidate = None
    for name in ordered_variants:
        required = thresholds.get(name, thresholds.get("nano", 0.0))
        if vram_gib >= required:
            candidate = name
        else:
            break
    if candidate:
        return candidate
    if default in available:
        return default
    return ordered_variants[0]


def _resolve_manifest_entry(
    manifest: Dict[str, Any],
    slug: str,
    *,
    variant_override: Optional[str],
) -> Tuple[Dict[str, Any], Optional[str], Optional[float]]:
    raw_entry = manifest.get(slug)
    if raw_entry is None:
        available = ", ".join(sorted(manifest.keys()))
        raise RuntimeError(f"No artifact for '{slug}'. Available: {available}")

    if isinstance(raw_entry, dict) and "variants" in raw_entry:
        variants_obj = raw_entry.get("variants")
        if not isinstance(variants_obj, dict):
            raise RuntimeError(f"Manifest entry for '{slug}' has invalid variants data")
        available_variants = {
            key: value for key, value in variants_obj.items() if isinstance(value, dict)
        }
        if not available_variants:
            raise RuntimeError(f"Manifest entry for '{slug}' defines no valid variants")

        if variant_override:
            if variant_override not in available_variants:
                options = ", ".join(sorted(available_variants))
                raise RuntimeError(
                    f"Variant '{variant_override}' not available for '{slug}'. Options: {options}"
                )
            chosen = variant_override
            vram = detect_gpu_vram_gib()
            return available_variants[chosen], chosen, vram

        vram = detect_gpu_vram_gib()
        default_variant = raw_entry.get("default") if isinstance(raw_entry, dict) else None
        if default_variant and not isinstance(default_variant, str):
            default_variant = None
        chosen = _recommend_variant(
            available_variants,
            vram_gib=vram,
            default=default_variant,
        )
        return available_variants[chosen], chosen, vram

    if variant_override:
        raise RuntimeError(
            f"Manifest for '{slug}' has no variants; --variant '{variant_override}' is invalid."
        )
    if not isinstance(raw_entry, dict):
        raise RuntimeError(f"Manifest entry for '{slug}' has unexpected format")
    return raw_entry, None, None


def run(
    manifest_ref: str,
    slug_override: Optional[str] = None,
    *,
    variant_override: Optional[str] = None,
    force: bool = False,
) -> Tuple[Path, Path]:
    slug = slug_override or detect_platform_slug()
    manifest = read_manifest(manifest_ref)
    entry, chosen_variant, detected_vram = _resolve_manifest_entry(
        manifest,
        slug,
        variant_override=variant_override,
    )

    url = entry.get("url")
    if not url:
        raise RuntimeError(f"Manifest entry for '{slug}' missing 'url'")
    sha256 = entry.get("sha256")
    version = str(entry.get("version") or "unknown")
    build_label = entry.get("build")
    build_label = str(build_label) if build_label else None

    if chosen_variant:
        if detected_vram:
            print(
                f"Detected ~{detected_vram:.1f} GiB of VRAM; installing '{chosen_variant}' variant."
            )
        else:
            print(f"Unable to detect VRAM; defaulting to '{chosen_variant}' variant.")
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
        "--variant",
        default=os.getenv("NOCTICS_INSTALLER_VARIANT"),
        help="Override variant selection when the manifest provides multiple options.",
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
            variant_override=args.variant,
            force=args.force,
        )
    except Exception as exc:
        print(f"Installer failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
