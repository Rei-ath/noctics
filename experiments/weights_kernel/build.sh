#!/usr/bin/env sh
set -e

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OUT="$ROOT/build"

CC=${CC:-clang}
CFLAGS=${CFLAGS:-"-O3 -march=armv8.2-a+dotprod -DNDEBUG"}

mkdir -p "$OUT"

$CC $CFLAGS -std=c11 -o "$OUT/weights_kernel" "$ROOT/main.c"
$CC $CFLAGS -std=c11 -o "$OUT/gate_train" "$ROOT/gate_train.c"

echo "built: $OUT/weights_kernel"
echo "built: $OUT/gate_train"
