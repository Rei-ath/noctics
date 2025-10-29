# PyInstaller spec for packaging the private Noctics Core binary.
# The build script sets NOCTICS_ROOT, NOCTICS_MODEL_PATH, and NOCTICS_MODEL_NAME
# before invoking PyInstaller so we can wire in the bundled assets.

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

_root_override = os.environ.get("NOCTICS_ROOT")
if _root_override:
    ROOT = Path(_root_override)
else:
    try:
        ROOT = Path(__file__).resolve().parents[1]
    except NameError:
        ROOT = Path.cwd()
CORE_ROOT = ROOT / "core"

if not CORE_ROOT.exists():
    raise SystemExit("Noctics core submodule missing. Run: git submodule update --init --recursive")

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(CORE_ROOT))

model_path_str = os.environ.get("NOCTICS_MODEL_PATH")
if not model_path_str:
    raise SystemExit("NOCTICS_MODEL_PATH environment variable must point to the GGUF model")

MODEL_PATH = Path(model_path_str).resolve()
if not MODEL_PATH.exists():
    raise SystemExit(f"GGUF model not found: {MODEL_PATH}")

MODEL_NAME = os.environ.get("NOCTICS_MODEL_NAME", MODEL_PATH.name)
MODEL_FILES = [
    (str(MODEL_PATH), f"resources/models/{MODEL_NAME}"),
]

def package_data_for(package_name):
    records = []
    for src, dest in collect_data_files(package_name):
        records.append((src, dest))
    return records


def include_directory(relative_dir):
    records = []
    base = CORE_ROOT / relative_dir
    if not base.exists():
        return records
    for file_path in base.rglob("*"):
        if file_path.is_file():
            dest = str(file_path.relative_to(CORE_ROOT))
            records.append((str(file_path), dest))
    return records

DATAS = []
for package in ("central", "interfaces", "noxl", "noctics_cli", "instruments"):
    DATAS.extend(package_data_for(package))

HIDDEN_IMPORTS = []
for package in ("central", "interfaces", "noxl", "noctics_cli", "instruments"):
    HIDDEN_IMPORTS.extend(collect_submodules(package))
HIDDEN_IMPORTS = sorted(set(HIDDEN_IMPORTS))

for extra_dir in ("config", "datasets", "third_party", "models", "memory"):  # models may host prompt templates
    DATAS.extend(include_directory(extra_dir))

DATAS.extend(MODEL_FILES)

OLLAMA_BIN = ROOT / "assets" / "ollama" / "bin" / "ollama"
OLLAMA_LIB = ROOT / "assets" / "ollama" / "lib" / "libollama.so"
OLLAMA_MODELS = ROOT / "assets" / "ollama" / "models"
RUNTIME_DIR = ROOT / "assets" / "runtime"
RUNTIME_HOOKS = [str(ROOT / "release" / "runtime_env.py")]

BINARIES = []
if OLLAMA_BIN.exists():
    BINARIES.append((str(OLLAMA_BIN), "resources/ollama/bin"))
if OLLAMA_LIB.exists():
    BINARIES.append((str(OLLAMA_LIB), "resources/ollama/lib"))

if OLLAMA_MODELS.exists():
    for file_path in OLLAMA_MODELS.rglob("*"):
        if file_path.is_file():
            relative = file_path.relative_to(OLLAMA_MODELS)
            dest_dir = Path("resources/ollama/models") / relative.parent
            DATAS.append((str(file_path), str(dest_dir)))

if RUNTIME_DIR.exists():
    for file_path in RUNTIME_DIR.rglob("*"):
        if file_path.is_file():
            relative = file_path.relative_to(RUNTIME_DIR)
            dest_dir = Path("resources/runtime") / relative.parent
            DATAS.append((str(file_path), str(dest_dir)))

for src, _ in DATAS:
    if not Path(src).is_file():
        raise SystemExit(f"Data entry is not a file: {src}")

for src, _ in BINARIES:
    if not Path(src).is_file():
        raise SystemExit(f"Binary entry is not a file: {src}")

analysis = Analysis(
    [str(CORE_ROOT / "main.py")],
    pathex=[str(CORE_ROOT)],
    binaries=BINARIES,
    datas=DATAS,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=RUNTIME_HOOKS,
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    name="noctics-core",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    exclude_binaries=True,
)

COLLECT(
    exe,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="noctics-core",
)
RUNTIME_HOOKS = [str(ROOT / "release" / "runtime_env.py")]
