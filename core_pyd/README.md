# Noctics Core (Binary)

This package vendors the compiled `central`, `config`, `inference`, `interfaces`,
and `noxl` modules so downstream tooling can `import central` without access to
the Python source.

Importing `core_pyd` automatically registers the compiled modules inside
`sys.modules`. When the pure-Python sources under `core/` are unavailable,
install this package and the Noctics CLI will fall back to the binary runtime.

## Rebuilding the payload

1. Activate the bundled Nuitka environment: `source ../pyd-env/bin/activate`.
2. Run `PYTHONPATH=../core python -m nuitka --module ../core/<package>` for each
   package (`central`, `config`, `inference`, `interfaces`, `noxl`) or use
   `scripts/push_core_pyd.sh`.
3. Copy the resulting `*.so` artifacts into this directory.
4. Build the wheel: `python -m build` (install `build` if it is not present).
