"""Generate original, dependency-free 24px emoji and a chat launcher icon."""

from pathlib import Path
import struct
import zlib


ROOT = Path(__file__).resolve().parents[1] / "badge" / "apps" / "attendee_chat"
GOLD = (255, 211, 92, 255)
DARK = (29, 34, 54, 255)
GREEN = (129, 247, 179, 255)
PINK = (255, 112, 149, 255)
WHITE = (239, 244, 255, 255)


def canvas(width, height):
    return [[(0, 0, 0, 0) for _ in range(width)] for _ in range(height)]


def rectangle(pixels, x, y, width, height, ink):
    for row in range(y, y + height):
        for column in range(x, x + width):
            pixels[row][column] = ink


def circle(pixels, x, y, radius, ink):
    for row in range(max(0, y - radius), min(len(pixels), y + radius + 1)):
        for column in range(max(0, x - radius), min(len(pixels[0]), x + radius + 1)):
            if (column - x) ** 2 + (row - y) ** 2 <= radius ** 2:
                pixels[row][column] = ink


def bitmap(pixels, rows, ink, x=4, y=4, scale=1):
    for row, pattern in enumerate(rows):
        for column, bit in enumerate(pattern):
            if bit == "#":
                rectangle(pixels, x + column * scale, y + row * scale, scale, scale, ink)


def png(path, pixels):
    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    raw = b"".join(b"\0" + bytes(channel for pixel in row for channel in pixel) for row in pixels)
    header = struct.pack(">IIBBBBB", len(pixels[0]), len(pixels), 8, 6, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def build():
    smile = canvas(24, 24)
    circle(smile, 12, 12, 10, GOLD)
    rectangle(smile, 7, 8, 2, 3, DARK)
    rectangle(smile, 15, 8, 2, 3, DARK)
    bitmap(smile, ("#.......#", ".#.....#.", "..#####.."), DARK, 8, 14)

    heart = canvas(24, 24)
    bitmap(heart, (".##..##.", "########", "########", "########",
                   ".######.", "..####..", "...##..."), PINK, 4, 5, 2)

    thumb = canvas(24, 24)
    bitmap(thumb, ("....##..", "....##..", "...###..", "..#####.",
                   "#######.", "#######.", "#######.", "..####.."), GOLD, 4, 4, 2)
    rectangle(thumb, 3, 12, 4, 9, GREEN)

    wave = canvas(24, 24)
    bitmap(wave, ("...#.#....", ".#.#.#.#..", ".#.#.#.#..", ".#######..",
                  ".#######..", "..######.#", "..########", "...######.",
                  "...#####..", "....###..."), GOLD, 2, 2, 2)
    rectangle(wave, 1, 1, 2, 2, GREEN)
    rectangle(wave, 20, 2, 2, 3, GREEN)

    star = canvas(24, 24)
    bitmap(star, ("....#....", "...###...", "...###...", "#########",
                  ".#######.", "..#####..", "..#####..", ".###.###.",
                  ".#.....#."), GOLD, 3, 3, 2)

    rocket = canvas(24, 24)
    bitmap(rocket, ("......###", ".....####", "....#####", "...#####.",
                    ".######..", "#######..", "######...", "..####...", "..###...."),
           WHITE, 3, 2, 2)
    circle(rocket, 15, 8, 2, (91, 166, 255, 255))
    bitmap(rocket, ("..##", ".###", "###.", "##.."), PINK, 1, 15, 2)

    sheet = canvas(144, 24)
    for index, sprite in enumerate((smile, heart, thumb, wave, star, rocket)):
        for y, row in enumerate(sprite):
            sheet[y][index * 24:(index + 1) * 24] = row
    png(ROOT / "emoji.png", sheet)

    icon = canvas(24, 24)
    rectangle(icon, 0, 0, 24, 24, DARK)
    rectangle(icon, 3, 4, 18, 13, GREEN)
    bitmap(icon, ("###", "##.", "#.."), GREEN, 5, 17)
    for x in (7, 11, 15):
        rectangle(icon, x, 9, 2, 3, DARK)
    png(ROOT / "icon.png", icon)


if __name__ == "__main__":
    build()
