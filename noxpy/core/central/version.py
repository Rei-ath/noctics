"""Nox version information."""

from importlib import metadata

__all__ = ["__version__"]

try:  # pragma: no cover - only hit when installed as a package
    __version__ = metadata.version("noctics-core")
except metadata.PackageNotFoundError:  # pragma: no cover - development fallback
    __version__ = "0.1.39"
