#!/usr/bin/env bash
set -euo pipefail

VENV="${HOME}/.venvs/noctics-test"
CORE_WHEEL="dist/noctics_core_pinaries-0.1.39-py3-none-any.whl"
CLI_WHEEL="dist/noctics-0.1.39-py3-none-any.whl"

if [[ ! -f "${CORE_WHEEL}" || ! -f "${CLI_WHEEL}" ]]; then
  echo "Could not find ${CORE_WHEEL} or ${CLI_WHEEL}" >&2
  exit 1
fi

python -m venv "${VENV}"
source "${VENV}/bin/activate"

python -m pip install -U pip
python -m pip install --force-reinstall "${CORE_WHEEL}" "${CLI_WHEEL}"

echo "Wheels installed. Run 'noctics --setup' if you haven't already, then 'noctics chat --stream'."
