#!/usr/bin/env python3
import argparse
import struct
from pathlib import Path

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

QK_K = 256
K_SCALE_SIZE = 12
BLOCK_Q4_K_BYTES = 2 + 2 + K_SCALE_SIZE + (QK_K // 2)  # d + dmin + scales + qs


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
    ap.add_argument("--tensor", required=True, help="tensor name or substring")
    ap.add_argument("--rows", type=int, default=None)
    ap.add_argument("--cols", type=int, default=None)
    ap.add_argument("--out", required=True, help="output .bin path")
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
        data_offset = f.tell()
        if data_offset % alignment != 0:
            data_offset += alignment - (data_offset % alignment)

    match = None
    for name, dims, ttype, offset in tensors:
        if args.tensor in name:
            match = (name, dims, ttype, offset)
            break
    if not match:
        raise SystemExit(f"tensor not found: {args.tensor}")

    name, dims, ttype, offset = match
    if ttype != 12:  # Q4_K
        raise SystemExit(f"tensor {name} is type {ttype}, need Q4_K (type 12)")

    if len(dims) < 2:
        raise SystemExit(f"tensor {name} dims {dims} not matrix-like")

    n = int(dims[0])
    k = int(dims[1])
    rows = args.rows or n
    cols = args.cols or k

    if rows > n or cols > k:
        raise SystemExit("rows/cols exceed tensor dims")
    if cols % QK_K != 0:
        raise SystemExit("cols must be multiple of 256 for Q4_K")

    row_blocks_total = k // QK_K
    row_blocks = cols // QK_K
    row_bytes = row_blocks_total * BLOCK_Q4_K_BYTES

    out_path = Path(args.out)
    with path.open("rb") as f, out_path.open("wb") as out:
        base = data_offset + offset
        for r in range(rows):
            row_off = base + r * row_bytes
            f.seek(row_off)
            for _ in range(row_blocks):
                block = f.read(BLOCK_Q4_K_BYTES)
                if len(block) != BLOCK_Q4_K_BYTES:
                    raise SystemExit("unexpected EOF")
                qs = block[4 + K_SCALE_SIZE:]
                for b in qs:
                    lo = (b & 0x0F) - 8
                    hi = (b >> 4) - 8
                    out.write(struct.pack("b", lo))
                    out.write(struct.pack("b", hi))

    print(f"wrote {out_path} rows={rows} cols={cols} tensor={name} version={version}")


if __name__ == "__main__":
    main()
