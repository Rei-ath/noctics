"""Set default runtime environment for the packaged CLI."""

import os
from pathlib import Path


def _load_env_file(env_path: Path) -> None:
    try:
        content = env_path.read_text(encoding="utf-8")
    except Exception:
        return
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, value.strip())


_dist_root = Path(__file__).resolve().parents[2]
_env_file = _dist_root / "resources" / "env" / ".env"
if _env_file.exists():
    _load_env_file(_env_file)

# Default to the local Ollama endpoint; users can still override this via their
# own environment variables when they run the binary or via the packaged .env.
os.environ.setdefault("CENTRAL_LLM_URL", "http://127.0.0.1:11434/api/generate")
_ollama_models = _dist_root / "resources" / "ollama" / "models"
if _ollama_models.exists():
    os.environ.setdefault("OLLAMA_MODELS", str(_ollama_models))

_runtime_meta = _dist_root / "resources" / "runtime"
_primary_alias_file = _runtime_meta / "primary_alias.txt"
_lite_alias_file = _runtime_meta / "lite_alias.txt"

if _primary_alias_file.exists():
    os.environ.setdefault("CENTRAL_LLM_MODEL", _primary_alias_file.read_text().strip() or "gemma3:latest")
else:
    _alias_manifest = _ollama_models / "manifests" / "registry.ollama.ai" / "library" / "noctics-edge" / "latest"
    if _alias_manifest.exists():
        os.environ.setdefault("CENTRAL_LLM_MODEL", "noctics-edge:latest")
    else:
        os.environ.setdefault("CENTRAL_LLM_MODEL", "gemma3:latest")

if _lite_alias_file.exists():
    os.environ.setdefault("NOCTICS_EDGE_LITE_MODEL", _lite_alias_file.read_text().strip())
