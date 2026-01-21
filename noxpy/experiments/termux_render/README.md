# Terminal Render Demo (Termux approved)

Text mode doesn’t have to be boring. This experiment slings gradients and images
inside a terminal, perfect for a future Noctics TUI.

## Run it
```bash
cd experiments/termux_render
python demo_render.py            # add --animate or an image path if you’re feeling spicy
```

Controls:
- `q` quit
- `a` toggle auto animation
- space → single-step the gradient
- `g` gradient mode
- `i` render the image (if provided)
- `r` reset the phase

Want instant motion?
```bash
python demo_render.py --animate
```

Drop in an image (needs Pillow):
```bash
pip install pillow
python demo_render.py ~/Pictures/sample.jpg --width 120 --height 40 --animate
```

## Why Nox cares
- Modern terminals (Termux, kitty, wezterm) speak 24-bit color and Unicode blocks.
- You can craft dashboards, previews, even faux-UI widgets without leaving text land.
- Swap the renderer for Kitty/Sixel escapes later to push real image frames.
- Tie the pipeline to session logs or hardware stats and you’ve got a hacker HUD ready for primetime.
