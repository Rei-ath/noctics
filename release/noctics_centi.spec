# PyInstaller spec for the centi scale build (Qwen3 8B default)

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

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
    return collect_data_files(package_name)


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
for package in ("central", "interfaces", "noxl", "noctics_cli"):
    DATAS.extend(package_data_for(package))

for extra_dir in ("config", "datasets", "third_party", "models", "memory"):
    DATAS.extend(include_directory(extra_dir))

DATAS.extend(MODEL_FILES)

env_override = os.environ.get("NOCTICS_ENV_FILE", ROOT / ".env.centi")
ENV_FILE = Path(env_override).expanduser()
if ENV_FILE.exists():
    DATAS.append((str(ENV_FILE), "resources/env/.env"))

OLLAMA_ROOT = ROOT / "assets" / "ollama"
RUNTIME_DIR = ROOT / "assets" / "runtime"
RUNTIME_HOOKS = [str(ROOT / "release" / "runtime_env.py")]

BINARIES = []
ollama_bin = OLLAMA_ROOT / "bin" / "ollama"
ollama_lib = OLLAMA_ROOT / "lib" / "libollama.so"
if ollama_bin.exists():
    BINARIES.append((str(ollama_bin), "resources/ollama/bin"))
if ollama_lib.exists():
    BINARIES.append((str(ollama_lib), "resources/ollama/lib"))

ollama_models = OLLAMA_ROOT / "models"
if ollama_models.exists():
    for file_path in ollama_models.rglob("*"):
        if file_path.is_file():
            relative = file_path.relative_to(ollama_models)
            dest_dir = Path("resources/ollama/models") / relative.parent
            DATAS.append((str(file_path), str(dest_dir)))

if RUNTIME_DIR.exists():
    for file_path in RUNTIME_DIR.rglob("*"):
        if file_path.is_file():
            relative = file_path.relative_to(RUNTIME_DIR)
            dest_dir = Path("resources/runtime") / relative.parent
            DATAS.append((str(file_path), str(dest_dir)))

for src, _ in DATAS + BINARIES:
    if not Path(src).is_file():
        raise SystemExit(f"Missing bundle file: {src}")

analysis = Analysis(
    [str(CORE_ROOT / "main.py")],
    pathex=[str(CORE_ROOT), str(ROOT)],
    binaries=BINARIES,
    datas=DATAS,
    hiddenimports=[],
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
    name="centi-noctics",
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
    name="centi-noctics",
)
