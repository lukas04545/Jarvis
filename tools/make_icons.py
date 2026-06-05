#!/usr/bin/env python3
"""Generate J.A.R.V.I.S. PWA app icons — dependency-free.

Rasterises the ◈ brand mark (amber diamond outline + filled core on a near-black
field) directly to PNG using only the stdlib (zlib + struct), so icons can be
(re)built in any environment with no image libraries and no network.

Run:  python3 tools/make_icons.py
"""
from __future__ import annotations

import os
import struct
import zlib

BG = (10, 13, 18)        # --panel  near-black
AMBER = (255, 158, 27)   # --amber
CYAN = (56, 225, 255)    # --cyan

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "static", "icons")


def _clamp(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _disk(d: float, r: float, feather: float) -> float:
    """Coverage of a filled diamond of radius r, antialiased over `feather`."""
    if d <= r:
        return 1.0
    return _clamp((r + feather - d) / feather)


def _band(d: float, lo: float, hi: float, feather: float) -> float:
    """Coverage of a ring band [lo,hi], antialiased over `feather`."""
    if lo <= d <= hi:
        return 1.0
    if d < lo:
        return _clamp((d - (lo - feather)) / feather)
    return _clamp((hi + feather - d) / feather)


def render(size: int, pad: float) -> bytes:
    """Return raw RGBA scanlines for an `size`x`size` icon.

    `pad` is the fraction of the canvas reserved as a maskable safe-zone margin.
    """
    cx = cy = (size - 1) / 2.0
    R = size * (0.5 - pad)          # outer diamond vertex radius (px)
    feather = 1.4 / R               # ~1.4px edge softening in metric units
    raw = bytearray()
    for y in range(size):
        raw.append(0)               # PNG filter byte: none
        dy = abs(y - cy) / R
        for x in range(size):
            d = abs(x - cx) / R + dy   # L1 (diamond) metric: 0 centre → 1 vertex
            px = BG
            ring = _band(d, 0.80, 0.90, feather)
            core = _disk(d, 0.40, feather)
            amber_cov = max(ring, core)
            if amber_cov > 0:
                px = _lerp(px, AMBER, amber_cov)
            center = _disk(d, 0.15, feather)
            if center > 0:
                px = _lerp(px, CYAN, center)
            raw += bytes((px[0], px[1], px[2], 255))
    return bytes(raw)


def write_png(path: str, size: int, pad: float = 0.0) -> None:
    raw = render(size, pad)
    comp = zlib.compress(raw, 9)

    def chunk(typ: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + typ
            + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", comp))
        f.write(chunk(b"IEND", b""))
    print(f"  wrote {os.path.relpath(path, HERE)} ({size}x{size})")


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    write_png(os.path.join(OUT, "icon-192.png"), 192)
    write_png(os.path.join(OUT, "icon-512.png"), 512)
    # Maskable variants keep the mark inside the ~80% safe zone.
    write_png(os.path.join(OUT, "icon-maskable-192.png"), 192, pad=0.12)
    write_png(os.path.join(OUT, "icon-maskable-512.png"), 512, pad=0.12)
    write_png(os.path.join(OUT, "apple-touch-icon.png"), 180, pad=0.06)
    print("icons generated.")


if __name__ == "__main__":
    main()
