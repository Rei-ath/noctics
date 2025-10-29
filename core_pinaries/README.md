# Noctics Core (binary build)

Version `0.1.39` mirrors the public `noctics-core` tree at the matching commit
count. Install this when you need `import central` without exposing sources.

## What’s inside
- Nuitka-built extensions for `central`, `config`, `inference`, `interfaces`, `noxl`
- An `__init__` shim that registers the modules automatically
- A `.pth` file so Python finds us the second we hit site-packages

## Install me
```bash
pip install core_pinaries-*.whl
python -c "import central, noxl; print(central.__file__)"
```
If that prints a `.so`, congrats—you’re running the dark build.

## Rebuild recipe
1. `source ../pyd-env/bin/activate`
2. `PYTHONPATH=../core python -m nuitka --module ../core/<package>` for each of:
   `central`, `config`, `inference`, `interfaces`, `noxl`
   (or just run `../scripts/push_core_pinaries.sh`)
3. Drop the new `*.so` files into this directory
4. `python -m pip install build` if needed, then `python -m build`

Ship the wheel alongside the source release, sign both, and sleep better knowing
your intern can’t pop open the core logic.
