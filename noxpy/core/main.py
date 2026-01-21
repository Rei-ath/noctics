"""PyInstaller entrypoint for packaged Noctics binaries.

This module mirrors the repository-level ``main.py`` so that bundled
executables can launch the same multitool CLI.
"""

from __future__ import annotations

import sys
from typing import Sequence


def _run(argv: Sequence[str]) -> int:
    """Delegate to the shared CLI entrypoint, falling back to the bundled core CLI."""

    try:
        from noctics_cli.multitool import main as cli_main  # type: ignore
    except ImportError:
        from central.cli.simple import main as core_cli_main

        return core_cli_main(list(argv))
    return cli_main(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
