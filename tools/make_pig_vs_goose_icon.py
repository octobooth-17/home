"""Rebuild Pig vs Goose's 24x24 menu icon using only the standard library."""

import struct
import zlib
from pathlib import Path


SIZE = 24
SKY = (176, 228, 230)
INK = (36, 47, 61)
PINK = (247, 146, 171)
WHITE = (255, 252, 235)
BLUE = (45, 154, 216)
ORANGE = (249, 167, 65)
pixels = [[SKY for _ in range(SIZE)] for _ in range(SIZE)]


def box(x, y, w, h, color):
    for yy in range(max(0, y), min(SIZE, y + h)):
        for xx in range(max(0, x), min(SIZE, x + w)):
            pixels[yy][xx] = color


def circle(x, y, radius, color):
    for yy in range(SIZE):
        for xx in range(SIZE):
            if (xx - x) ** 2 + (yy - y) ** 2 <= radius ** 2:
                pixels[yy][xx] = color


def chunk(kind, data):
    payload = kind + data
    return (struct.pack(">I", len(data)) + payload
            + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF))


def main():
    box(0, 20, 24, 4, BLUE)
    circle(5, 15, 5, INK)
    circle(5, 14, 5, PINK)
    box(1, 7, 3, 5, PINK)
    box(7, 7, 3, 5, PINK)
    box(7, 14, 5, 3, (234, 107, 145))
    box(8, 15, 1, 1, INK)
    box(7, 11, 1, 2, INK)
    box(17, 7, 4, 11, WHITE)
    box(16, 5, 6, 5, WHITE)
    box(14, 8, 4, 2, ORANGE)
    box(17, 7, 1, 1, INK)
    circle(20, 17, 4, WHITE)
    box(18, 21, 2, 1, ORANGE)
    circle(11, 3, 3, BLUE)
    box(10, 1, 1, 2, WHITE)
    box(11, 6, 1, 1, BLUE)
    raw = b"".join(b"\0" + bytes(c for pixel in row for c in pixel) for row in pixels)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    destination = Path(__file__).resolve().parents[1] / "badge/apps/pig_vs_goose/icon.png"
    destination.write_bytes(png)
    print("Created", destination)


if __name__ == "__main__":
    main()
