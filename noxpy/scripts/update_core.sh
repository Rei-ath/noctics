#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE_DIR="$ROOT_DIR/core"
BRANCH="${1:-main}"

if [[ ! -e "$CORE_DIR/.git" ]]; then
  echo "[update_core] Initialize the submodule first: git submodule update --init" >&2
  exit 1
fi

echo "[update_core] Updating noctics-core to branch ${BRANCH}" >&2

git -C "$CORE_DIR" fetch origin "$BRANCH"
git -C "$CORE_DIR" checkout "$BRANCH"
git -C "$CORE_DIR" pull --ff-only origin "$BRANCH"

git -C "$ROOT_DIR" add core

echo "[update_core] noctics-core now at $(git -C "$CORE_DIR" rev-parse --short HEAD)" >&2
