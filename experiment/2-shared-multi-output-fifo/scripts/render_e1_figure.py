#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the E1 2x2 topology figure (PNG, no ASCII/mermaid)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1240, 660
BG = (250, 251, 253)
INK = (32, 38, 48)
MUTED = (90, 100, 115)
BLUE = (219, 234, 254)
BLUE_L = (59, 130, 246)
GREEN = (220, 252, 231)
GREEN_L = (34, 197, 94)
ORANGE = (255, 237, 213)
ORANGE_L = (249, 115, 22)
PURPLE = (237, 233, 254)
PURPLE_L = (139, 92, 246)
GREY = (148, 163, 184)


def font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def box(draw, xy, fill, outline, r=14, width=3):
    draw.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)


def text(draw, xy, s, size=18, bold=False, fill=INK, anchor="mm"):
    draw.multiline_text(
        xy, s, font=font(size, bold), fill=fill, anchor=anchor, align="center",
        spacing=4,
    )


def arrow(draw, pts, color=GREY, width=3, head=10):
    for a, b in zip(pts, pts[1:]):
        draw.line([a, b], fill=color, width=width)
    # Arrowhead on the last segment.
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    if abs(x2 - x1) >= abs(y2 - y1):
        sign = 1 if x2 >= x1 else -1
        p1 = (x2 - sign * head, y2 - head // 2)
        p2 = (x2 - sign * head, y2 + head // 2)
        p3 = (x2, y2)
    else:
        sign = 1 if y2 >= y1 else -1
        p1 = (x2 - head // 2, y2 - sign * head)
        p2 = (x2 + head // 2, y2 - sign * head)
        p3 = (x2, y2)
    draw.polygon([p1, p2, p3], fill=color)


def main() -> int:
    out_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "figures"
        / "e1-2x2-topology.png"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    text(d, (W // 2, 36), "E1: 2x2 switch with per-input 1W/2R shared FIFOs",
         28, True, INK)

    # Inputs.
    for i, y in enumerate((150, 430)):
        box(d, (40, y - 55, 150, y + 55), GREEN, GREEN_L)
        text(d, (95, y), f"IN{i}\n1 flit/cyc", 18, True)
        arrow(d, [(150, y), (215, y)], GREEN_L)
        text(d, (183, y - 22), "write", 13, False, MUTED)

    # Shared FIFOs.
    for i, y in enumerate((150, 430)):
        box(d, (220, y - 90, 500, y + 90), BLUE, BLUE_L)
        text(d, (360, y - 38), f"Shared FIFO {i}\n1W / 2R", 20, True)
        text(d, (360, y + 10), "CELL_NUM shared cells\nVC-linked queues", 15, False, MUTED)
        text(d, (360, y + 58), "read port 0  |  read port 1", 14, True, BLUE_L)
        # Two read-port arrows toward the output arbiters.
        for out_idx, yy in ((0, 170), (1, 450)):
            mid_x = 585
            arrow(
                d,
                [(500, y - 35 if out_idx == 0 else y + 35),
                 (mid_x, y - 35 if out_idx == 0 else y + 35),
                 (mid_x, yy),
                 (620, yy)],
                BLUE_L,
                2,
            )

    # Output arbiters.
    for o, y in enumerate((170, 450)):
        box(d, (620, y - 55, 790, y + 55), ORANGE, ORANGE_L)
        text(d, (705, y - 12), f"OUT ARB {o}", 20, True)
        text(d, (705, y + 24), "2:1  |  packet lock", 13, False, MUTED)
        arrow(d, [(790, y), (910, y)], ORANGE_L)
        text(d, (850, y - 22), "1 flit/cyc", 13, False, MUTED)

    # Outputs.
    for o, y in enumerate((170, 450)):
        box(d, (910, y - 55, 1050, y + 55), PURPLE, PURPLE_L)
        text(d, (980, y), f"OUT{o}\n1 flit/cyc", 18, True)

    # Notes.
    text(
        d,
        (W // 2, 610),
        "Both outputs can read the same input in one cycle through different VCs; "
        "a VC is never served by two outputs.",
        14,
        False,
        MUTED,
    )
    img.save(str(out_path), format="PNG")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
