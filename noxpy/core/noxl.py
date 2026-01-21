"""Compatibility shim to launch the Noxl CLI."""

from __future__ import annotations

from noxl.cli import main


if __name__ == "__main__":
    import sys

    sys.exit(main())
