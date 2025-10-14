# Terminal Rendering Demo (Termux-friendly)

Quick experiment showing how far you can push visuals inside a text terminal—perfect for a Noctics-style TUI.

## Usage

Run the interactive viewer:
```bash
cd experiments/termux_render
python demo_render.py  # add --animate or an image path if you like
```
Controls:
- `q` quit
- `a` toggle auto gradient animation
- space: step one gradient frame
- `g` switch to gradient mode
- `i` show the loaded image (if provided)
- `r` reset the gradient phase

Pass `--animate` to start animating immediately. Provide an image path to render it alongside the gradient (requires Pillow):
```bash
python demo_render.py ~/Pictures/sample.jpg --width 120 --height 40 --animate
```
Install Pillow if you need image support:
```bash
pip install pillow
```

## Why it matters

- Termux (and most modern terminals) understand 24‑bit color + Unicode, so you can draw “GUI-ish” elements, previews, even simple animations without leaving text mode.
- Adapt `demo_render.py` to feed frames from Noctics sessions, hardware telemetry, or helper outputs to get a hacker-friendly dashboard.
- For higher fidelity later, swap the renderer to Kitty/Sixel escape codes—the same pipeline can emit true image frames once the terminal supports it.
