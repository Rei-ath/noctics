#!/usr/bin/env python3
"""Package Noctics runtime bundles and update installer manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
import zipfile


DEFAULT_ARCHIVE_PREFIX = "noctics-core"
DEFAULT_BUNDLE_NAME = "noctics-core"
DEFAULT_MANIFEST_NAME = "installer_manifest.json"
README_FILENAME = "README.txt"
README_TEMPLATE = """Noctics Runtime
=================

Version: {VERSION}

This archive packages the Noctics core runtime, models, and CLI.

Quick start:
  1. Extract the archive to a writable directory.
  2. Ensure the `noctics` shim (created during install) is on your PATH.
  3. Run `noctics --setup` once to configure your preferred instrument.

Releases embed a default LayMA runtime. Override it with environment variables:
  NOX_LLM_URL            Remote inference endpoint (e.g. OpenAI, Scale)
  NOX_OPENAI_MODEL       Remote model id to target (default: gpt-4o-mini)

Need help? Check docs/installer_design.md inside the repository you pulled this from.
"""


@dataclass
class PackagingArgs:
    dist_dir: Path
    output_dir: Path
    bundle_name: str
    archive_prefix: str
    slug: str
    os_name: str
    extension: str
    manifest: Optional[Path]
    url_prefix: Optional[str]
    artifact_url: Optional[str]
    skip_readme: bool
    readme_template: Optional[Path]
    version: Optional[str]
    build_label: Optional[str]
    variant: Optional[str]


def _detect_os_name() -> str:
    value = sys.platform
    if value.startswith("linux"):
        return "linux"
    if value == "darwin":
        return "macos"
    if value in {"win32", "cygwin"}:
        return "windows"
    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def _detect_architecture() -> str:
    machine = platform.machine().lower()
    aliases = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "i386": "x86",
        "i686": "x86",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv8": "arm64",
        "armv7l": "armhf",
        "armv7": "armhf",
    }
    return aliases.get(machine, machine or "unknown")


def _extension_for_os(os_name: str) -> str:
    mapping = {
        "linux": ".tar.gz",
        "macos": ".zip",
        "windows": ".zip",
    }
    if os_name not in mapping:
        raise RuntimeError(f"Unsupported OS for packaging: {os_name}")
    return mapping[os_name]


def _compute_slug(os_name: str, arch: str) -> str:
    if not arch:
        raise RuntimeError("Unable to determine architecture for slug computation")
    return f"{os_name}-{arch}"


def _ensure_readme(dist_dir: Path, template: Optional[Path], version: Optional[str]) -> None:
    target = dist_dir / README_FILENAME
    if target.exists():
        return
    if template:
        content = template.read_text(encoding="utf-8")
    else:
        content = README_TEMPLATE
    if version:
        content = content.replace("{VERSION}", str(version))
    else:
        content = content.replace("{VERSION}", "unknown")
    target.write_text(content, encoding="utf-8")


def _add_directory_to_zip(zf: zipfile.ZipFile, source: Path, root_name: str) -> None:
    for path in sorted(source.rglob("*")):
        arcname = Path(root_name) / path.relative_to(source)
        if path.is_dir():
            zf.write(path, arcname.as_posix())
        else:
            zf.write(path, arcname.as_posix())


def _create_archive(args: PackagingArgs) -> Path:
    archive_name = f"{args.archive_prefix}-{args.slug}{args.extension}"
    archive_path = args.output_dir / archive_name
    if archive_path.exists():
        archive_path.unlink()

    if args.extension == ".tar.gz":
        with tarfile.open(archive_path, "w:gz") as tf:
            tf.add(args.dist_dir, arcname=args.bundle_name)
    elif args.extension == ".zip":
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            _add_directory_to_zip(zf, args.dist_dir, args.bundle_name)
    else:
        raise RuntimeError(f"Unsupported archive extension: {args.extension}")

    return archive_path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _update_manifest(
    manifest: Path,
    slug: str,
    url: str,
    sha256: str,
    size: int,
    *,
    version: Optional[str] = None,
    build: Optional[str] = None,
    variant: Optional[str] = None,
) -> None:
    data: Dict[str, Dict[str, object]] = {}
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError(f"Manifest file {manifest} does not contain an object")
    entry: Dict[str, object] = {"url": url, "sha256": sha256, "size": size}
    if version:
        entry["version"] = version
    if build:
        entry["build"] = build
    if variant:
        slug_entry = data.get(slug)
        if not isinstance(slug_entry, dict):
            slug_entry = {}
        variants = slug_entry.get("variants")
        if not isinstance(variants, dict):
            variants = {}
        variants[variant] = entry
        slug_entry["variants"] = variants
        slug_entry.setdefault("default", variant)
        data[slug] = slug_entry
    else:
        data[slug] = entry
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_url(artifact_name: str, url_prefix: Optional[str], artifact_url: Optional[str]) -> str:
    if artifact_url:
        return artifact_url
    if url_prefix:
        prefix = url_prefix.rstrip("/")
        return f"{prefix}/{artifact_name}"
    return artifact_name


def package_runtime(
    dist_dir: Path,
    output_dir: Path,
    *,
    bundle_name: Optional[str] = None,
    archive_prefix: Optional[str] = None,
    slug: Optional[str] = None,
    os_name: Optional[str] = None,
    arch: Optional[str] = None,
    manifest: Optional[Path] = None,
    url_prefix: Optional[str] = None,
    artifact_url: Optional[str] = None,
    skip_readme: bool = False,
    readme_template: Optional[Path] = None,
    version: Optional[str] = None,
    build: Optional[str] = None,
    variant: Optional[str] = None,
) -> Path:
    if not dist_dir.exists():
        raise RuntimeError(f"Distribution directory missing: {dist_dir}")
    if not dist_dir.is_dir():
        raise RuntimeError(f"Distribution path is not a directory: {dist_dir}")

    detected_os = os_name or _detect_os_name()
    detected_arch = arch or _detect_architecture()
    computed_slug = slug or _compute_slug(detected_os, detected_arch)

    extension = _extension_for_os(detected_os)

    archive_prefix = archive_prefix or DEFAULT_ARCHIVE_PREFIX
    bundle_name = bundle_name or dist_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)

    if not skip_readme:
        _ensure_readme(dist_dir, readme_template, version)

    packaging_args = PackagingArgs(
        dist_dir=dist_dir,
        output_dir=output_dir,
        bundle_name=bundle_name,
        archive_prefix=archive_prefix,
        slug=computed_slug,
        os_name=detected_os,
        extension=extension,
        manifest=manifest,
        url_prefix=url_prefix,
        artifact_url=artifact_url,
        skip_readme=skip_readme,
        readme_template=readme_template,
        version=version,
        build_label=build,
        variant=variant,
    )
    archive_path = _create_archive(packaging_args)
    checksum = _sha256(archive_path)
    archive_name = archive_path.name
    url = _resolve_url(archive_name, url_prefix, artifact_url)

    if manifest:
        _update_manifest(
            manifest,
            computed_slug,
            url,
            checksum,
            archive_path.stat().st_size,
            version=version,
            build=build,
            variant=variant,
        )

    version_suffix = f", version={version}" if version else ""
    print(f"[package_installer] Created {archive_path} (sha256={checksum}{version_suffix})")
    if manifest:
        print(f"[package_installer] Updated manifest {manifest} for slug {computed_slug}")
    return archive_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package Noctics runtime bundles for the installer.")
    parser.add_argument(
        "--dist-dir",
        default=Path("dist") / DEFAULT_BUNDLE_NAME,
        type=Path,
        help="Path to the PyInstaller output directory to package.",
    )
    parser.add_argument(
        "--output-dir",
        default=Path("dist"),
        type=Path,
        help="Directory to write archives and manifests.",
    )
    parser.add_argument(
        "--bundle-name",
        default=None,
        help="Folder name to use inside the archive (defaults to dist dir name).",
    )
    parser.add_argument(
        "--archive-prefix",
        default=DEFAULT_ARCHIVE_PREFIX,
        help="Archive filename prefix (defaults to noctics-core).",
    )
    parser.add_argument(
        "--slug",
        default=None,
        help="Override platform slug (defaults to auto-detected os-arch).",
    )
    parser.add_argument(
        "--os-name",
        default=None,
        help="Override detected OS name (linux/macos/windows).",
    )
    parser.add_argument(
        "--arch",
        default=None,
        help="Override detected architecture (x86_64/arm64/armhf/etc).",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        type=Path,
        help="Manifest file to update (JSON). Defaults to dist/installer_manifest.json if provided.",
    )
    parser.add_argument(
        "--url-prefix",
        default=None,
        help="Prefix to prepend to archive filenames when writing manifest URLs.",
    )
    parser.add_argument(
        "--artifact-url",
        default=None,
        help="Explicit URL to use in the manifest instead of computing from prefix.",
    )
    parser.add_argument(
        "--skip-readme",
        action="store_true",
        help="Skip auto-generating README.txt when missing.",
    )
    parser.add_argument(
        "--readme-template",
        default=None,
        type=Path,
        help="Optional path to a template for README.txt.",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Version string to embed in manifest entries and README placeholders.",
    )
    parser.add_argument(
        "--build",
        default=None,
        help="Build identifier recorded alongside the manifest entry.",
    )
    parser.add_argument(
        "--variant",
        default=None,
        help="Variant label recorded under the manifest slug (e.g. nano, micro).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    manifest = args.manifest
    if manifest is None and args.url_prefix:
        manifest = args.output_dir / DEFAULT_MANIFEST_NAME
    try:
        package_runtime(
            Path(args.dist_dir),
            Path(args.output_dir),
            bundle_name=args.bundle_name,
            archive_prefix=args.archive_prefix,
            slug=args.slug,
            os_name=args.os_name,
            arch=args.arch,
            manifest=manifest,
            url_prefix=args.url_prefix,
            artifact_url=args.artifact_url,
            skip_readme=args.skip_readme,
            readme_template=args.readme_template,
            version=args.version,
            build=args.build,
            variant=args.variant,
        )
    except Exception as exc:
        print(f"[package_installer] Packaging failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
