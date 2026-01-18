#!/usr/bin/env python3
"""
Continuously stream a model file to keep pages hot.
This is a stress tool to test memory-bandwidth contention.
"""

import argparse
import os
import time


def parse_bytes(value: str) -> int:
    s = value.strip().lower()
    if s.endswith("k"):
        return int(float(s[:-1]) * 1024)
    if s.endswith("m"):
        return int(float(s[:-1]) * 1024 * 1024)
    if s.endswith("g"):
        return int(float(s[:-1]) * 1024 * 1024 * 1024)
    return int(s)


def stream_file(path: str, chunk_size: int, duration: float, report_sec: float, quiet: bool) -> None:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    size = os.path.getsize(path)
    buf = bytearray(chunk_size)
    view = memoryview(buf)

    start = time.monotonic()
    last = start
    bytes_read = 0
    checksum = 0

    with open(path, "rb", buffering=0) as f:
        while True:
            f.seek(0)
            while True:
                n = f.readinto(view)
                if n == 0:
                    break
                bytes_read += n
                checksum ^= buf[0]
                now = time.monotonic()
                if report_sec > 0 and now - last >= report_sec and not quiet:
                    elapsed = now - last
                    rate = (bytes_read / elapsed) / (1024 * 1024)
                    print(f"stream: {rate:.1f} MiB/s (file={size} bytes)")
                    bytes_read = 0
                    last = now
                if duration > 0 and now - start >= duration:
                    if not quiet:
                        total = now - start
                        print(f"done: {total:.2f}s checksum={checksum}")
                    return


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream model file to keep pages hot.")
    parser.add_argument("--model", required=True, help="Path to model file")
    parser.add_argument("--chunk", default="8M", help="Read chunk size (e.g. 4M, 16M)")
    parser.add_argument("--duration", type=float, default=0.0, help="Seconds to run (0 = infinite)")
    parser.add_argument("--report-sec", type=float, default=1.0, help="Report interval seconds (0 = silent)")
    parser.add_argument("--quiet", action="store_true", help="Suppress periodic output")
    args = parser.parse_args()

    chunk_size = parse_bytes(args.chunk)
    try:
        stream_file(args.model, chunk_size, args.duration, args.report_sec, args.quiet)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
