"""Repository-level driver for the Noctics multitool CLI."""

from __future__ import annotations

import sys

from noctics_cli.multitool import main as cli_main


def main(argv: list[str]) -> int:
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
