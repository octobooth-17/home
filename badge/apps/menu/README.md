# Menu

The badge's home screen: a launcher that lists every installed app and starts the one you pick.

## Usage

Use the LEFT, RIGHT, UP, and DOWN buttons to move between app icons and SELECT to launch the highlighted app. Apps appear automatically when they contain an `__init__.py` and a 24x24 `icon.png`.

## Launcher clock

The top-right status bar shows a small 12-hour Pacific-time clock with AM/PM beside the
battery, with US daylight saving transitions applied automatically. It is
menu-only: apps, full-screen photos, and full-screen celebrations have no clock
overlay. The clock moves and fades with the existing launcher status bar.

The internal RTC must contain UTC. It retains time across resets while powered,
but after power loss it may need setting again; an unset RTC shows `--:--`,
not uptime. To synchronize from a Windows computer with Python and mpremote,
discover the badge with `mpremote devs`, then substitute its port below:

```powershell
$utc = [DateTime]::UtcNow
$weekday = (([int]$utc.DayOfWeek + 6) % 7)
mpremote connect COM14 exec "import machine; machine.RTC().datetime(($($utc.Year),$($utc.Month),$($utc.Day),$weekday,$($utc.Hour),$($utc.Minute),$($utc.Second),0))"
mpremote connect COM14 reset
```

Do not use `mpremote rtc --set`: it writes the computer's local time, not UTC.
No network connection or credentials are required. For a different timezone,
adjust `menu_clock.py`'s offset and daylight saving rule before deploying.

When updating a customized physical badge, back up its menu first and patch
only the `menu_clock` import and draw call in its own `__init__.py`, then copy
`menu_clock.py` beside it. Leave `ui.mpy`, `src/ui.py`, other compiled modules,
assets, and `main.py` unchanged; the clock uses the existing compiled UI.
