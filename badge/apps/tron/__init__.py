"""Neon light-cycle duels for the Universe 2026 badge."""

import os
import sys

APP_DIR = "/system/apps/tron"
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

from arena import Arena, UP, DOWN, LEFT, RIGHT

badge.mode(HIRES | VSYNC)
screen.antialias = image.OFF
screen.fill_rule = image.EVEN_ODD

BACKGROUND = color.rgb(5, 9, 20)
PANEL = color.rgb(10, 20, 36)
GRID = color.rgb(15, 33, 49)
BORDER = color.rgb(32, 71, 90)
CYAN = color.rgb(45, 237, 255)
ORANGE = color.rgb(255, 149, 56)
WHITE = color.rgb(226, 249, 255)
MUTED = color.rgb(123, 154, 174)
TRAILS = (CYAN, ORANGE)
GLOWS = (color.rgb(12, 72, 90), color.rgb(86, 44, 23))

CELL = 4
COLS = (screen.width - 16) // CELL
ROWS = (screen.height - 64) // CELL
FIELD_X = (screen.width - COLS * CELL) // 2
FIELD_Y = 38
FIELD_W, FIELD_H = COLS * CELL, ROWS * CELL

arena = Arena(COLS, ROWS)
state = "title"
wins = [0, 0]
result_age = 0
BUTTONS = ((BUTTON_UP, UP), (BUTTON_DOWN, DOWN),
           (BUTTON_LEFT, LEFT), (BUTTON_RIGHT, RIGHT))


def text(label, x, y, pen=WHITE, large=False):
    screen.font = font.ziplock if large else font.nope
    screen.pen = pen
    screen.text(label, x, y)


def centered(label, y, pen=WHITE, large=False):
    screen.font = font.ziplock if large else font.nope
    width, _ = screen.measure_text(label)
    text(label, (screen.width - width) // 2, y, pen, large)


def right_text(label, y, pen):
    screen.font = font.nope
    width, _ = screen.measure_text(label)
    text(label, screen.width - 10 - width, y, pen)


def start_round():
    global state, result_age
    arena.reset()
    state = "playing"
    result_age = 0


def draw_path(points, pen, thickness):
    screen.pen = pen
    inset = (CELL - thickness) // 2
    for index in range(max(1, len(points) - 1)):
        ax, ay = points[index]
        bx, by = points[min(index + 1, len(points) - 1)]
        screen.rectangle(
            FIELD_X + min(ax, bx) * CELL + inset,
            FIELD_Y + min(ay, by) * CELL + inset,
            abs(ax - bx) * CELL + thickness,
            abs(ay - by) * CELL + thickness,
        )


def draw_arena():
    screen.pen = BACKGROUND
    screen.clear()
    screen.pen = GRID
    for x in range(FIELD_X, FIELD_X + FIELD_W + 1, CELL * 4):
        screen.line(x, FIELD_Y, x, FIELD_Y + FIELD_H)
    for y in range(FIELD_Y, FIELD_Y + FIELD_H + 1, CELL * 4):
        screen.line(FIELD_X, y, FIELD_X + FIELD_W, y)
    screen.pen = BORDER
    screen.line(FIELD_X - 1, FIELD_Y - 1, FIELD_X + FIELD_W, FIELD_Y - 1)
    screen.line(FIELD_X - 1, FIELD_Y + FIELD_H, FIELD_X + FIELD_W, FIELD_Y + FIELD_H)
    screen.line(FIELD_X - 1, FIELD_Y, FIELD_X - 1, FIELD_Y + FIELD_H)
    screen.line(FIELD_X + FIELD_W, FIELD_Y, FIELD_X + FIELD_W, FIELD_Y + FIELD_H)
    for rider in range(2):
        draw_path(arena.paths[rider], GLOWS[rider], CELL)
        draw_path(arena.paths[rider], TRAILS[rider], 2)
        x, y = arena.heads[rider]
        px, py = FIELD_X + x * CELL, FIELD_Y + y * CELL
        screen.pen = TRAILS[rider]
        screen.rectangle(px - 1, py - 1, CELL + 2, CELL + 2)
        screen.pen = WHITE
        screen.rectangle(px + 1, py + 1, 2, 2)

    text("YOU %02d" % wins[0], 10, 10, CYAN)
    centered("LIGHT CYCLES", 9, WHITE)
    right_text("CPU %02d" % wins[1], 10, ORANGE)
    if state == "playing" and not arena.countdown:
        centered("D-PAD STEER   MENU PAUSE", screen.height - 16, MUTED)
        centered("%02d:%02d" % (arena.elapsed // 60000, arena.elapsed // 1000 % 60),
                 24, MUTED)


def card(top, height):
    screen.pen = BORDER
    screen.rectangle(23, top - 1, screen.width - 46, height + 2)
    screen.pen = PANEL
    screen.rectangle(24, top, screen.width - 48, height)


def draw_title():
    # Original circuit artwork doubles as a preview of the two trail colors.
    for points, rider in (
        ([(3, ROWS - 3), (19, ROWS - 3), (19, ROWS - 8), (28, ROWS - 8)], 0),
        ([(COLS - 4, 3), (COLS - 20, 3), (COLS - 20, 1), (COLS - 29, 1)], 1),
    ):
        draw_path(points, GLOWS[rider], CELL)
        draw_path(points, TRAILS[rider], 2)
    card(61, 130)
    centered("T R O N", 73, CYAN, True)
    centered("LIGHT-CYCLE DUEL", 96, WHITE)
    centered("Leave a trail. Outlast the CPU.", 115, MUTED)
    centered("D-pad to steer / no reverse", 130, MUTED)
    centered("SELECT TO RACE", 153, CYAN)
    centered("BY kawaigram", 177, MUTED)
    centered("HOME EXIT", screen.height - 16, MUTED)


def draw_countdown():
    card(86, 62)
    centered(str((arena.countdown + 799) // 800), 96, CYAN, True)
    centered("GET READY / D-PAD TO STEER", 127, MUTED)


def draw_pause():
    card(78, 89)
    centered("PAUSED", 91, CYAN, True)
    centered("SELECT / MENU TO RESUME", 123, WHITE)
    centered("BACK TO TITLE", 144, MUTED)


def draw_result():
    for x, y in arena.crashes:
        px = FIELD_X + max(0, min(COLS - 1, x)) * CELL + CELL // 2
        py = FIELD_Y + max(0, min(ROWS - 1, y)) * CELL + CELL // 2
        radius = 4 + min(12, result_age // 40)
        screen.pen = WHITE if result_age < 200 else ORANGE
        screen.line(px - radius, py - radius, px + radius, py + radius)
        screen.line(px - radius, py + radius, px + radius, py - radius)
    card(70, 105)
    heading, pen = {
        "player": ("YOU WIN", CYAN),
        "cpu": ("GRID CRASH", ORANGE),
        "draw": ("DOUBLE CRASH", WHITE),
    }[arena.result]
    centered(heading, 82, pen, True)
    centered("BOTH CYCLES DOWN" if arena.result == "draw"
             else ("CPU ELIMINATED" if arena.result == "player" else "CPU WINS THIS ROUND"),
             109, MUTED)
    centered("SELECT TO RACE AGAIN", 136, WHITE)
    centered("BACK TO TITLE", 156, MUTED)


def update():
    global state, result_age
    dt = max(0, min(250, badge.ticks_delta))
    if state == "title":
        if badge.pressed(BUTTON_SELECT):
            start_round()
    elif state == "paused":
        if badge.pressed(BUTTON_BACK):
            state = "title"
        elif badge.pressed(BUTTON_SELECT) or badge.pressed(BUTTON_MENU):
            state = "playing"
    elif state == "over":
        result_age += dt
        if badge.pressed(BUTTON_BACK):
            state = "title"
        elif result_age >= 400 and badge.pressed(BUTTON_SELECT):
            start_round()
    elif badge.pressed(BUTTON_MENU) or badge.pressed(BUTTON_BACK):
        state = "paused"
    else:
        for button, direction in BUTTONS:
            if badge.pressed(button):
                arena.turn(direction)
        arena.advance(dt)
        if arena.result is not None:
            state = "over"
            result_age = 0
            if arena.result == "player":
                wins[0] += 1
            elif arena.result == "cpu":
                wins[1] += 1

    draw_arena()
    if state == "title":
        draw_title()
    elif state == "paused":
        draw_pause()
    elif state == "over":
        draw_result()
    elif arena.countdown:
        draw_countdown()


run(update)
