# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
Draw the launcher's icon: a few lines of transcript, one word struck out.

    venv/bin/python scripts/app_icon.py OUT.png

Writes a 1024×1024 PNG; make-app.sh turns it into an .icns. Colours are the
light theme's tokens from web/static/style.css.
"""
import sys

from PIL import Image, ImageDraw

SIZE = 1024
SS = 4                      # supersample, then downscale for clean edges
PAPER = "#f7f4ef"
LINE = "#e3ddd2"
INK = "#46423c"
CUT = "#a33f38"
CUT_BG = "#f9e3e0"

# Word widths per line, in tile units; the marked word is the one cut.
LINES = [
    [150, 90, 210],
    [110, ("cut", 170), 140],
    [190, 120],
]


def draw(path: str) -> None:
    s = SIZE * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def px(v):
        return int(v * SS)

    # macOS icon grid: an 824-unit rounded tile centred on the 1024 canvas
    tile = (100, 100, 924, 924)
    d.rounded_rectangle([px(v) for v in tile], radius=px(185),
                        fill=PAPER, outline=LINE, width=px(6))

    word_h, gap, line_gap = 64, 34, 70
    top = 512 - (len(LINES) * word_h + (len(LINES) - 1) * line_gap) / 2
    for row, words in enumerate(LINES):
        y = top + row * (word_h + line_gap)
        x = 200
        for w in words:
            cut = isinstance(w, tuple)
            width = w[1] if cut else w
            box = [px(x), px(y), px(x + width), px(y + word_h)]
            d.rounded_rectangle(box, radius=px(word_h / 2),
                                fill=CUT_BG if cut else INK)
            if cut:
                mid = y + word_h / 2
                d.rounded_rectangle(
                    [px(x - 14), px(mid - 9), px(x + width + 14), px(mid + 9)],
                    radius=px(9), fill=CUT)
            x += width + gap

    img.resize((SIZE, SIZE), Image.LANCZOS).save(path)


if __name__ == "__main__":
    draw(sys.argv[1] if len(sys.argv) > 1 else "icon.png")
