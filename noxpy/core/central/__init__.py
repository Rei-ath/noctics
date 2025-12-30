"""Nox core package."""

from __future__ import annotations

from .version import __version__


__all__ = ["main", "parse_args", "__version__"]


def main(argv):
    try:
        from noctics_cli import main as _main  # type: ignore
    except ImportError:
        from central.cli.simple import main as _main

    return _main(argv)


def parse_args(argv):
    try:
        from noctics_cli import parse_args as _parse_args  # type: ignore
    except ImportError:
        from central.cli.simple import parse_args as _parse_args

    return _parse_args(argv)
