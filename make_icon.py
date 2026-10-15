from __future__ import annotations

import math
import os
import struct
import zlib

SIZES = (16, 20, 24, 32, 48, 64, 256)
INSET = 0.05
SHEEN = 0.06
RIM = 0.90
GLOW = 0.25
TILE_TOP = (64, 140, 255)
TILE_BOTTOM = (16, 58, 150)
GLYPH = (255, 255, 255)
SPAN = 46.0
BIG = (0.330, 0.070, 0.035)
MID = (0.345, 0.078, 0.040)
SMALL = (0.370, 0.095, 0.050)
TINY = (0.385, 0.102, 0.054)
MICRO = (0.400, 0.108, 0.058)
GLYPHS = {16: MICRO, 20: TINY, 24: SMALL, 32: MID}


def _mix(c1: tuple, c2: tuple, t: float) -> tuple:
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return (c1[0] + (c2[0] - c1[0]) * t, c1[1] + (c2[1] - c1[1]) * t, c1[2] + (c2[2] - c1[2]) * t)


def _tile(x: float, y: float, n: float = 4.2) -> float:
    a = 0.5 - INSET
    return (abs((x - 0.5) / a) ** n + abs((y - 0.5) / a) ** n) ** (1.0 / n)


def _arc(px: float, py: float, cx: float, cy: float, r: float, a0: float, a1: float) -> float:
    dx, dy = px - cx, py - cy
    d = math.sqrt(dx * dx + dy * dy)
    ang = math.atan2(dy, dx)
    lo, hi = (a0, a1) if a0 <= a1 else (a1, a0)
    if lo <= ang <= hi:
        return abs(d - r)
    d0 = math.sqrt((px - (cx + r * math.cos(lo))) ** 2 + (py - (cy + r * math.sin(lo))) ** 2)
    d1 = math.sqrt((px - (cx + r * math.cos(hi))) ** 2 + (py - (cy + r * math.sin(hi))) ** 2)
    return d0 if d0 < d1 else d1


def _glyph(g: tuple) -> tuple:
    r1, sw, dot = g
    r2 = r1 / 2.0
    cy = 0.5 + (r1 + sw / 2.0 - dot) / 2.0
    a0 = math.radians(-90.0 - SPAN)
    a1 = math.radians(-90.0 + SPAN)
    return (0.5, cy, r1, r2, sw / 2.0, dot, a0, a1)


def _sample(fx: float, fy: float, gl: tuple, size: int):
    f = _tile(fx, fy)
    if f > 1.0:
        return None
    col = _mix(TILE_TOP, TILE_BOTTOM, fy * 0.62 + (1.0 - fx) * 0.38)
    k = 1.0 + SHEEN * (1.0 - fy)
    col = (col[0] * k, col[1] * k, col[2] * k)
    if 0.84 < f <= 0.955:
        t = (0.955 - f) / 0.115 * GLOW * (1.0 - fy) ** 2
        col = _mix(col, (255, 255, 255), t)
    if f > 0.955:
        col = (col[0] * RIM, col[1] * RIM, col[2] * RIM)
    cx, cy, r1, r2, hw, dot, a0, a1 = gl
    for r in (r1, r2):
        d = _arc(fx, fy, cx, cy, r, a0, a1) - hw
        a = 0.5 - d * size
        if a > 0:
            col = _mix(col, GLYPH, 1.0 if a > 1.0 else a)
    dd = math.sqrt((fx - cx) ** 2 + (fy - cy) ** 2) - dot
    a = 0.5 - dd * size
    if a > 0:
        col = _mix(col, GLYPH, 1.0 if a > 1.0 else a)
    return col


def render(size: int, ss: int | None = None, g: tuple | None = None) -> bytes:
    if ss is None:
        ss = 4 if size <= 64 else 3
    if g is None:
        g = GLYPHS.get(size, BIG)
    gl = _glyph(g)
    px = bytearray(size * size * 4)
    n = ss * ss
    for y in range(size):
        for x in range(size):
            hit = r = gg = b = 0
            for sy in range(ss):
                for sx in range(ss):
                    c = _sample((x + (sx + 0.5) / ss) / size, (y + (sy + 0.5) / ss) / size, gl, size)
                    if c is None:
                        continue
                    hit += 1
                    r += c[0]
                    gg += c[1]
                    b += c[2]
            i = (y * size + x) * 4
            if hit:
                px[i] = min(255, max(0, int(r / hit + 0.5)))
                px[i + 1] = min(255, max(0, int(gg / hit + 0.5)))
                px[i + 2] = min(255, max(0, int(b / hit + 0.5)))
                px[i + 3] = int(255 * hit / n + 0.5)
    return bytes(px)


def to_png(size: int, rgba: bytes) -> bytes:
    raw = b"".join(b"\x00" + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def to_bmp(size: int, rgba: bytes) -> bytes:
    head = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    rows = []
    for y in range(size - 1, -1, -1):
        row = bytearray()
        for x in range(size):
            i = (y * size + x) * 4
            row += bytes((rgba[i + 2], rgba[i + 1], rgba[i], rgba[i + 3]))
        rows.append(bytes(row))
    stride = ((size + 31) // 32) * 4
    mask = bytearray()
    for y in range(size - 1, -1, -1):
        bits = bytearray(stride)
        for x in range(size):
            if rgba[(y * size + x) * 4 + 3] < 128:
                bits[x // 8] |= 0x80 >> (x % 8)
        mask += bits
    return head + b"".join(rows) + bytes(mask)


def to_ico(images: list) -> bytes:
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = data = b""
    for size, blob in images:
        w = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(blob), offset)
        data += blob
        offset += len(blob)
    return head + entries + data


def main() -> None:
    base = os.path.dirname(os.path.abspath(__file__))
    images = []
    for size in SIZES:
        rgba = render(size)
        images.append((size, to_png(size, rgba) if size >= 256 else to_bmp(size, rgba)))
        if size == 256:
            with open(os.path.join(base, "icon-preview.png"), "wb") as fh:
                fh.write(images[-1][1])
    with open(os.path.join(base, "app.ico"), "wb") as fh:
        fh.write(to_ico(images))
    print("已生成 app.ico（%d 个尺寸）" % len(images))


if __name__ == "__main__":
    main()