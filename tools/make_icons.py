"""Generate the extension's PNG icons (stdlib only, no Pillow needed).

    python3 tools/make_icons.py

Draws a rounded coral square with the white download glyph from icon.svg, supersampled
for smooth edges.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "extension" / "icons"
SIZES = (16, 32, 48, 128)
SUPERSAMPLE = 4

TOP = (255, 162, 76)      # gradient start (amber)
BOTTOM = (255, 106, 61)   # gradient end (coral)
WHITE = (255, 255, 255)


def _inside_rounded_rect(x: float, y: float, radius: float) -> bool:
    cx = min(max(x, radius), 1 - radius)
    cy = min(max(y, radius), 1 - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2


def _dist_to_segment(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5


GLYPH_SCALE = 0.80  # fraction of the tile the 24-unit glyph spans


def _to_tile(x: float, y: float) -> tuple[float, float]:
    """Map extension/icons/icon.svg coordinates (0-24) onto the unit tile."""
    return 0.5 + (x - 12) / 24 * GLYPH_SCALE, 0.5 + (y - 12) / 24 * GLYPH_SCALE


def _arc(cx: float, cy: float, r: float, start_deg: float, end_deg: float, steps: int = 12):
    return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
            for a in (start_deg + (end_deg - start_deg) * i / steps for i in range(steps + 1))]


def _segments(points):
    return [(*_to_tile(*a), *_to_tile(*b)) for a, b in zip(points, points[1:])
            if math.dist(a, b) > 1e-9]  # arcs repeat their joining points


# Same shapes as icon.svg: shaft, arrow head, rounded tray.
STROKES = (
    _segments([(12, 3.5), (12, 15)])
    + _segments([(7.5, 10.5), (12, 15), (16.5, 10.5)])
    + _segments([(4.5, 13.5), (4.5, 16), *_arc(8, 16, 3.5, 180, 90),
                 (16, 19.5), *_arc(16, 16, 3.5, 90, 0), (19.5, 13.5)])
)
STROKE_HALF_WIDTH = 1.0 / 24 * GLYPH_SCALE  # stroke-width 2 in the SVG
_half_width = STROKE_HALF_WIDTH  # widened at tiny sizes so strokes stay crisp


def _sample(x: float, y: float) -> tuple[int, int, int, int]:
    if not _inside_rounded_rect(x, y, 0.22):
        return (0, 0, 0, 0)
    if any(_dist_to_segment(x, y, *s) <= _half_width for s in STROKES):
        return (*WHITE, 255)
    t = (x + y) / 2
    return (*(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)), 255)


def render(size: int) -> bytes:
    global _half_width
    _half_width = max(STROKE_HALF_WIDTH, 0.75 / size)
    rows = []
    n = SUPERSAMPLE
    for py in range(size):
        row = bytearray([0])  # PNG filter type: none
        for px in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(n):
                for sx in range(n):
                    r, g, b, a = _sample((px + (sx + 0.5) / n) / size, (py + (sy + 0.5) / n) / size)
                    acc[0] += r * a
                    acc[1] += g * a
                    acc[2] += b * a
                    acc[3] += a
            alpha = acc[3] / (n * n)
            color = [round(c / acc[3]) if acc[3] else 0 for c in acc[:3]]
            row += bytes([*color, round(alpha)])
        rows.append(bytes(row))
    return _png(size, size, b"".join(rows))


def _png(width: int, height: int, raw: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        (OUT_DIR / f"icon{size}.png").write_bytes(render(size))
        print(f"wrote icon{size}.png")


if __name__ == "__main__":
    main()
