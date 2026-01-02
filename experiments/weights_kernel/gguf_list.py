#!/usr/bin/env python3
import argparse
import struct
from collections import Counter
from pathlib import Path

GGML_TYPES = {
    0: "F32",
    1: "F16",
    2: "Q4_0",
    3: "Q4_1",
    6: "Q5_0",
    7: "Q5_1",
    8: "Q8_0",
    9: "Q8_1",
    10: "Q2_K",
    11: "Q3_K",
    12: "Q4_K",
    13: "Q5_K",
    14: "Q6_K",
    15: "Q8_K",
    16: "IQ2_XXS",
    17: "IQ2_XS",
    18: "IQ3_XXS",
    19: "IQ1_S",
    20: "IQ4_NL",
    21: "IQ3_S",
    22: "IQ2_S",
    23: "IQ4_XS",
    24: "I8",
    25: "I16",
    26: "I32",
    27: "I64",
    28: "F64",
    29: "IQ1_M",
    30: "BF16",
    34: "TQ1_0",
    35: "TQ2_0",
    39: "MXFP4",
}

GGUF_TYPE_SIZES = {
    0: 1,  # u8
    1: 1,  # i8
    2: 2,  # u16
    3: 2,  # i16
    4: 4,  # u32
    5: 4,  # i32
    6: 4,  # f32
    7: 1,  # bool
    8: 0,  # string
    9: 0,  # array
    10: 8, # u64
    11: 8, # i64
    12: 8, # f64
}


def read_u32(f):
    return struct.unpack("<I", f.read(4))[0]


def read_u64(f):
    return struct.unpack("<Q", f.read(8))[0]


def read_str(f):
    n = read_u64(f)
    data = f.read(n)
    return data.decode("utf-8")


def skip_kv(f, n_kv):
    alignment = 32
    for _ in range(n_kv):
        key = read_str(f)
        vtype = read_u32(f)
        if vtype == 8:  # string
            _ = read_str(f)
        elif vtype == 9:  # array
            atype = read_u32(f)
            n = read_u64(f)
            if atype == 8:  # string array
                for _ in range(n):
                    _ = read_str(f)
            else:
                size = GGUF_TYPE_SIZES.get(atype, 0)
                f.seek(size * n, 1)
        else:
            size = GGUF_TYPE_SIZES.get(vtype, 0)
            if key == "general.alignment" and vtype == 4:
                alignment = struct.unpack("<I", f.read(4))[0]
            else:
                f.seek(size, 1)
    return alignment


def read_tensor_meta(f, n_tensors):
    tensors = []
    for _ in range(n_tensors):
        name = read_str(f)
        n_dims = read_u32(f)
        dims = [read_u64(f) for _ in range(n_dims)]
        ttype = read_u32(f)
        offset = read_u64(f)
        tensors.append((name, dims, ttype, offset))
    return tensors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--filter", default=None, help="substring filter")
    args = ap.parse_args()

    path = Path(args.model)
    with path.open("rb") as f:
        magic = f.read(4)
        if magic != b"GGUF":
            raise SystemExit("not a GGUF file")
        version = read_u32(f)
        n_tensors = read_u64(f)
        n_kv = read_u64(f)
        alignment = skip_kv(f, n_kv)
        tensors = read_tensor_meta(f, n_tensors)

    counts = Counter()
    for name, dims, ttype, _ in tensors:
        counts[ttype] += 1

    print(f"version={version} tensors={n_tensors} kv={n_kv} alignment={alignment}")
    print("types:")
    for t, c in sorted(counts.items()):
        print(f"  {t} {GGML_TYPES.get(t, str(t))}: {c}")

    print("\nfirst tensors:")
    shown = 0
    for name, dims, ttype, _ in tensors:
        if args.filter and args.filter not in name:
            continue
        print(f"  {name} type={GGML_TYPES.get(ttype, str(ttype))} dims={list(dims)}")
        shown += 1
        if shown >= args.limit:
            break


if __name__ == "__main__":
    main()
