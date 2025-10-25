#!/usr/bin/env bash
set -euo pipefail

# Build noctics-core as binary extension modules and push the result.
# Relies on Nuitka producing .so/.pyd files for the major packages.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE_DIR="${ROOT_DIR}/core"
BUILD_DIR="${ROOT_DIR}/build/core_pinaries"
DIST_DIR="${ROOT_DIR}/core_pinaries"
PYTHON_BIN="${PYTHON_BIN:-python3}"
COMMIT_MSG="${1:-Build: refresh core binaries artifacts}"
TARGET_BRANCH="${TARGET_BRANCH:-$(git -C "${ROOT_DIR}" rev-parse --abbrev-ref HEAD)}"

if [[ ! -d "${CORE_DIR}" ]]; then
  echo "[push_core_pinaries] Expected core directory at ${CORE_DIR}" >&2
  exit 1
fi

echo "[push_core_pinaries] Using python interpreter: ${PYTHON_BIN}" >&2

if ! "${PYTHON_BIN}" -m nuitka --version >/dev/null 2>&1; then
  echo "[push_core_pinaries] Nuitka not found. Installing (requires build toolchain)..." >&2
  "${PYTHON_BIN}" -m pip install --quiet --upgrade nuitka
fi

EXT_SUFFIX="$("${PYTHON_BIN}" - <<'PY'
import sysconfig
print(sysconfig.get_config_var("EXT_SUFFIX"))
PY
)"

echo "[push_core_pinaries] Python extension suffix detected as ${EXT_SUFFIX}" >&2

"${PYTHON_BIN}" - <<'PY'
import pathlib, shutil
build_dir = pathlib.Path(r"${BUILD_DIR}")
dist_dir = pathlib.Path(r"${DIST_DIR}")
if build_dir.exists():
    shutil.rmtree(build_dir)
build_dir.mkdir(parents=True, exist_ok=True)
dist_dir.mkdir(parents=True, exist_ok=True)
for artifact in dist_dir.glob("*.so"):
    artifact.unlink()
pycache = dist_dir / "__pycache__"
if pycache.exists():
    shutil.rmtree(pycache)
PY

compile_module() {
  local module_name="$1"
  local package_path="${CORE_DIR}/${module_name}"

  if [[ ! -d "${package_path}" ]]; then
    echo "[push_core_pinaries] Package directory ${package_path} not found" >&2
    exit 1
  fi

  echo "[push_core_pinaries] Compiling package ${module_name}" >&2
  PYTHONPATH="${CORE_DIR}" "${PYTHON_BIN}" -m nuitka \
    --module "${package_path}" \
    --include-package="${module_name}" \
    --include-package-data="${module_name}" \
    --output-dir="${BUILD_DIR}"

  local built_file
  built_file="$(find "${BUILD_DIR}" -maxdepth 1 -type f -name "${module_name}*${EXT_SUFFIX}" | head -n1 || true)"

  if [[ -z "${built_file}" ]]; then
    echo "[push_core_pinaries] Failed to locate built artifact for ${module_name}" >&2
    exit 1
  fi

  cp "${built_file}" "${DIST_DIR}/"
}

compile_file_module() {
  local module_basename="$1"
  local source_path="$2"

  echo "[push_core_pinaries] Compiling ${module_basename} from ${source_path}" >&2
  PYTHONPATH="${CORE_DIR}" "${PYTHON_BIN}" -m nuitka \
    --module "${source_path}" \
    --output-dir="${BUILD_DIR}"

  local built_file
  built_file="$(find "${BUILD_DIR}" -maxdepth 1 -type f -name "${module_basename}*${EXT_SUFFIX}" | head -n1 || true)"

  if [[ -z "${built_file}" ]]; then
    echo "[push_core_pinaries] Failed to locate built artifact for ${module_basename}" >&2
    exit 1
  fi

  cp "${built_file}" "${DIST_DIR}/"
}

# Compile top-level packages.
declare -a PACKAGES=("central" "config" "inference" "interfaces" "noxl")
for package in "${PACKAGES[@]}"; do
  if [[ -d "${CORE_DIR}/${package}" ]]; then
    compile_module "${package}"
  else
    echo "[push_core_pinaries] Package ${package} not found in ${CORE_DIR}, skipping" >&2
  fi
done

# Compile standalone modules.
declare -a MODULE_FILES=()
for module_file in "${MODULE_FILES[@]}"; do
  if [[ -f "${CORE_DIR}/${module_file}" ]]; then
    module_name="${module_file%.py}"
    compile_file_module "${module_name}" "${CORE_DIR}/${module_file}"
  fi
done

echo "[push_core_pinaries] Staging compiled artifacts" >&2
git -C "${ROOT_DIR}" add "${DIST_DIR}"

if git -C "${ROOT_DIR}" diff --cached --quiet; then
  echo "[push_core_pinaries] No changes detected in ${DIST_DIR}; skipping commit/push" >&2
  exit 0
fi

echo "[push_core_pinaries] Committing with message: ${COMMIT_MSG}" >&2
git -C "${ROOT_DIR}" commit -m "${COMMIT_MSG}"

echo "[push_core_pinaries] Pushing to origin/${TARGET_BRANCH}" >&2
git -C "${ROOT_DIR}" push origin "${TARGET_BRANCH}"

echo "[push_core_pinaries] Done" >&2
