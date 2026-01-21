#!/usr/bin/env python3
"""Interactive terminal renderer using dense Unicode blocks (Termux-friendly)."""

from __future__ import annotations

import argparse
import curses
import os
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

try:
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Image = None  # type: ignore

RESET = "\033[0m"
UPPER_HALF = "▀"
FULL_BLOCK = "█"


# --------- color utilities --------------------------------------------------

def supports_truecolor() -> bool:
    colorterm = os.getenv("COLORTERM", "").lower()
    return "truecolor" in colorterm or "24bit" in colorterm


def rgb_to_fg(r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m"


def rgb_to_bg(r: int, g: int, b: int) -> str:
    return f"\033[48;2;{r};{g};{b}m"


# --------- frame packing ----------------------------------------------------

def to_terminal_frame(pixels: Sequence[Sequence[Tuple[int, int, int]]]) -> List[str]:
    """Pack two raster rows into one terminal line using half-block glyphs."""

    lines: List[str] = []
    row_iter = iter(pixels)

    for upper in row_iter:
        lower = next(row_iter, None)
        parts: List[str] = []
        for idx, (ru, gu, bu) in enumerate(upper):
            top = rgb_to_fg(ru, gu, bu)
            if lower is None or idx >= len(lower):
                parts.append(top + FULL_BLOCK)
                continue
            rl, gl, bl = lower[idx]
            bottom = rgb_to_bg(rl, gl, bl)
            parts.append(top + bottom + UPPER_HALF)
        lines.append("".join(parts) + RESET)
        if lower is None:
            break
    return lines


def gradient_pixels(width: int, height_px: int, phase: float) -> List[List[Tuple[int, int, int]]]:
    rows: List[List[Tuple[int, int, int]]] = []
    for y in range(height_px):
        row: List[Tuple[int, int, int]] = []
        for x in range(width):
            fx = x / max(width - 1, 1)
            fy = y / max(height_px - 1, 1)
            r = int(255 * abs((fx + phase) % 1.0))
            g = int(255 * abs((fy + phase * 0.5) % 1.0))
            b = int(255 * abs(((fx + fy) * 0.5 + phase * 0.25) % 1.0))
            row.append((r, g, b))
        rows.append(row)
    return rows


def gradient_frame(width: int, height: int, phase: float) -> List[str]:
    return to_terminal_frame(gradient_pixels(width, height * 2, phase))


def load_image_frame(path: Path, width: int, height: int) -> List[str]:
    if Image is None:
        raise RuntimeError("Install Pillow (`pip install pillow`) for image rendering.")
    image = Image.open(path).convert("RGB")
    image = image.resize((width, height * 2), Image.LANCZOS)
    pixels = list(image.getdata())
    rows: List[List[Tuple[int, int, int]]] = []
    for y in range(height * 2):
        start = y * width
        rows.append(pixels[start:start + width])
    return to_terminal_frame(rows)


# --------- interactive loop -------------------------------------------------

class FrameSource:
    def __init__(self, width: int, height: int, image_path: Optional[Path]) -> None:
        self.width = width
        self.height = height
        self.phase = 0.0
        self.image_lines = None
        if image_path is not None:
            self.image_lines = load_image_frame(image_path, width, height)

    def static_frame(self) -> List[str]:
        if self.image_lines is not None:
            return self.image_lines
        return gradient_frame(self.width, self.height, 0.0)

    def next_gradient(self, step: float = 0.02) -> List[str]:
        self.phase = (self.phase + step) % 1.0
        return gradient_frame(self.width, self.height, self.phase)


def draw_frame(stdscr: "curses._CursesWindow", lines: Sequence[str], status: str) -> None:
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()
    for idx, line in enumerate(lines):
        if idx >= max_y - 2:
            break
        try:
            stdscr.addstr(idx, 0, line)
        except curses.error:
            pass
    # status/info line
    try:
        stdscr.addstr(max_y - 2, 0, status[: max_x - 1])
    except curses.error:
        pass
    try:
        stdscr.addstr(
            max_y - 1,
            0,
            "[q]uit  [a]uto  [space] step  [g]radient  [i]mage  [r]eset"[: max_x - 1],
        )
    except curses.error:
        pass
    stdscr.refresh()


def interactive_loop(stdscr: "curses._CursesWindow", source: FrameSource, auto: bool) -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)
    if supports_truecolor():
        status_color = "Truecolor OK"
    else:
        status_color = "Truecolor uncertain (COLORTERM missing)"

    mode = "image" if source.image_lines is not None else "gradient"
    current = source.static_frame() if mode == "image" else source.next_gradient(step=0.0)
    draw_frame(stdscr, current, f"Mode: {mode} | Auto: {auto} | {status_color}")

    last_frame_at = time.time()

    while True:
        now = time.time()
        if auto and mode == "gradient" and now - last_frame_at >= 1.0 / 24.0:
            current = source.next_gradient()
            last_frame_at = now
            draw_frame(stdscr, current, f"Mode: gradient | Auto: {auto} | {status_color}")

        ch = stdscr.getch()
        if ch == -1:
            time.sleep(0.01)
            continue
        if ch in (ord("q"), ord("Q")):
            break
        if ch in (ord("a"), ord("A")):
            auto = not auto
            draw_frame(stdscr, current, f"Mode: {mode} | Auto: {auto} | {status_color}")
        elif ch == ord(" "):
            if mode == "gradient":
                current = source.next_gradient(step=0.05)
                last_frame_at = now
                draw_frame(stdscr, current, f"Mode: gradient | Auto: {auto} | {status_color}")
        elif ch in (ord("g"), ord("G")):
            mode = "gradient"
            current = source.next_gradient(step=0.0)
            last_frame_at = now
            draw_frame(stdscr, current, f"Mode: gradient | Auto: {auto} | {status_color}")
        elif ch in (ord("i"), ord("I")):
            if source.image_lines is not None:
                mode = "image"
                current = source.static_frame()
                draw_frame(stdscr, current, f"Mode: image | Auto: {auto} | {status_color}")
        elif ch in (ord("r"), ord("R")):
            source.phase = 0.0
            current = source.static_frame() if mode == "image" else source.next_gradient(step=0.0)
            last_frame_at = now
            draw_frame(stdscr, current, f"Mode: {mode} | Auto: {auto} | {status_color}")


# --------- entrypoint -------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive terminal renderer")
    parser.add_argument("path", nargs="?", help="Optional image path to display")
    parser.add_argument("--width", type=int, default=80, help="Frame width (columns)")
    parser.add_argument("--height", type=int, default=24, help="Frame height (terminal lines)")
    parser.add_argument("--animate", action="store_true", help="Start in auto gradient mode")
    args = parser.parse_args()

    image_path = Path(args.path).expanduser() if args.path else None
    if image_path is not None and not image_path.exists():
        parser.error(f"Image not found: {image_path}")

    source = FrameSource(args.width, args.height, image_path)

    try:
        curses.wrapper(interactive_loop, source, args.animate)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
