import ast
import calendar
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch


MENU = Path(__file__).resolve().parents[1] / "badge" / "apps" / "menu"


def timestamp(year, month, day, hour=0, minute=0):
    return calendar.timegm((year, month, day, hour, minute, 0))


class ClockTests(unittest.TestCase):
    def setUp(self):
        self.ui = SimpleNamespace(status_font="salty", dim_white="dim", OS_X=8, STATUS_HEIGHT=21)
        spec = importlib.util.spec_from_file_location("menu_clock", MENU / "menu_clock.py")
        self.clock = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"ui": self.ui}):
            spec.loader.exec_module(self.clock)
        # MicroPython's mktime is UTC; CPython's mktime depends on the host zone.
        self.clock.time = SimpleNamespace(
            gmtime=__import__("time").gmtime,
            mktime=calendar.timegm,
            time=Mock(return_value=timestamp(2026, 10, 28, 21, 42)),
        )
        self.screen = SimpleNamespace(
            width=320, measure_text=Mock(return_value=(37, 17)), text=Mock()
        )
        self.clock.screen = self.screen

    def test_pacific_time_and_midnight(self):
        self.assertEqual(self.clock.local_time(timestamp(2026, 10, 28, 21, 42))[3:5], (14, 42))
        self.assertEqual(self.clock.local_time(timestamp(2026, 1, 1, 7, 59))[:5], (2025, 12, 31, 23, 59))

    def test_daylight_transitions(self):
        for utc, expected in (
            (timestamp(2026, 3, 8, 9, 59), (1, 59)),
            (timestamp(2026, 3, 8, 10), (3, 0)),
            (timestamp(2026, 11, 1, 8, 59), (1, 59)),
            (timestamp(2026, 11, 1, 9), (1, 0)),
        ):
            with self.subTest(utc=utc):
                self.assertEqual(self.clock.local_time(utc)[3:5], expected)

    def test_unset_rtc(self):
        self.clock.time.time.return_value = timestamp(2021, 1, 1)
        with patch("builtins.print") as log:
            self.clock.draw()
            self.clock.draw()
        self.assertEqual(log.call_count, 1)
        self.assertEqual(self.screen.text.call_args.args[0], "--:--")
        self.clock.time.time.return_value = timestamp(2026, 10, 28, 21, 42)
        self.clock.draw()
        self.assertEqual(self.screen.text.call_args.args[0], "2:42 PM")

    def test_twelve_hour_format(self):
        for utc, expected in (
            (timestamp(2026, 10, 28, 7), "12:00 AM"),
            (timestamp(2026, 10, 28, 16, 5), "9:05 AM"),
            (timestamp(2026, 10, 28, 19), "12:00 PM"),
            (timestamp(2026, 10, 29, 6, 59), "11:59 PM"),
        ):
            with self.subTest(expected=expected):
                self.clock.time.time.return_value = utc
                self.clock.draw()
                self.assertEqual(self.screen.text.call_args.args[0], expected)

    def test_layout_animation_cache_and_minute_rollover(self):
        self.clock.draw()
        self.screen.text.assert_called_with("2:42 PM", 243, 3)
        self.assertGreater(243, 160 + 46 / 2)
        self.assertLess(243 + 37, 320 - 8 - 24)
        self.clock.draw(1.0)
        self.screen.text.assert_called_with("2:42 PM", 243, -18)
        self.assertEqual(self.screen.measure_text.call_count, 1)
        self.clock.time.time.return_value += 60
        self.clock.draw()
        self.screen.text.assert_called_with("2:43 PM", 243, 3)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((MENU / "__init__.py").read_text())
        update = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "update")
        self.apps = MagicMock()
        self.apps.__len__.return_value = 20
        self.apps.achievements.pending = None
        self.apps.picker = None
        self.apps.active = SimpleNamespace(path="/system/apps/snake", name="Snake")
        self.apps.active_index = 0
        self.apps.changed_at = 0
        self.env = dict(
            opening=None, viewer=None, celebration=None, mona=None,
            apps=self.apps, fade=255, FADE_STEP=30, IDLE_MS=600,
            badge=SimpleNamespace(pressed=Mock(return_value=False), ticks=1000),
            tilt=Mock(), ui=Mock(), menu_clock=Mock(), restore=Mock(),
            resume_sparkle=Mock(),
            BUTTON_LEFT=1, BUTTON_RIGHT=2, BUTTON_UP=3, BUTTON_DOWN=4,
            BUTTON_SELECT=5, BUTTON_BACK=6,
        )
        # Only the actual update callback is executed; no runtime/module startup.
        exec(compile(ast.Module(body=[update], type_ignores=[]), str(MENU / "__init__.py"), "exec"), self.env)

    def test_app_launch_returns_before_clock_draw(self):
        self.env["badge"].pressed.side_effect = lambda button: button == 5
        self.assertEqual(self.env["update"](), "/system/apps/snake")
        self.env["restore"].assert_called_once()
        self.env["menu_clock"].draw.assert_not_called()

    def test_fullscreen_photo_and_celebration_have_no_clock(self):
        for state in ("viewer", "celebration"):
            with self.subTest(state=state):
                self.env[state] = Mock(done=False, covering=True)
                self.env["update"]()
                self.env["menu_clock"].draw.assert_not_called()
                self.env[state] = None

    def test_menu_draws_clock_with_status_bar(self):
        self.env["update"]()
        self.env["ui"].draw_status.assert_called_once_with(0, 20, 0.0)
        self.env["menu_clock"].draw.assert_called_once_with(0.0)


if __name__ == "__main__":
    unittest.main()
