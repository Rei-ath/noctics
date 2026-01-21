"""Module entrypoint for ``python -m noctics_cli``."""

from __future__ import annotations

import sys

from .multitool import main


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
