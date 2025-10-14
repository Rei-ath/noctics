"""Project entrypoint for running the Noctics CLI from the repository root."""

from __future__ import annotations

import sys

from noctics_cli import main as cli_main


if __name__ == "__main__":
    raise SystemExit(cli_main(sys.argv[1:]))
