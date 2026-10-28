import time

import ui

# This badge uses the connected computer's Pacific timezone. Keep the RTC in UTC.
STANDARD_OFFSET = -8 * 3600
DAYLIGHT_OFFSET = 3600

_minute = None
_text = "--:--"
_width = None


def local_time(utc):
    year = time.gmtime(utc)[0]
    if year < 2026:
        return None
    march_weekday = time.gmtime(time.mktime((year, 3, 1, 0, 0, 0, 0, 0)))[6]
    november_weekday = time.gmtime(time.mktime((year, 11, 1, 0, 0, 0, 0, 0)))[6]
    march_day = 8 + (6 - march_weekday) % 7
    november_day = 1 + (6 - november_weekday) % 7
    # US daylight saving starts/ends at 02:00 local time, not UTC.
    start = time.mktime((year, 3, march_day, 2, 0, 0, 0, 0)) - STANDARD_OFFSET
    end = time.mktime((year, 11, november_day, 2, 0, 0, 0, 0)) - STANDARD_OFFSET - DAYLIGHT_OFFSET
    offset = STANDARD_OFFSET + (DAYLIGHT_OFFSET if start <= utc < end else 0)
    return time.gmtime(utc + offset)


def draw(hidden=0.0):
    global _minute, _text, _width
    minute = time.time() // 60
    screen.font = ui.status_font
    if minute != _minute:
        _minute = minute
        current = local_time(minute * 60)
        _text = (
            "%d:%02d %s" % (current[3] % 12 or 12, current[4], "AM" if current[3] < 12 else "PM")
            if current is not None else "--:--"
        )
        if current is None:
            print("Menu clock: RTC unset; synchronize UTC over USB.")
        _width = screen.measure_text(_text)[0]
    screen.pen = ui.dim_white
    right = screen.width - ui.OS_X - 24 - 8
    screen.text(_text, right - _width, 3 - round(ui.STATUS_HEIGHT * hidden))
