"""Host-side rules and frame-loop regression tests for the 2026 Tron app."""

import builtins
import importlib.util
from pathlib import Path
import random
import types
import unittest
from unittest.mock import Mock, patch


APP = Path(__file__).resolve().parents[1] / "badge" / "apps" / "tron"
SPEC = importlib.util.spec_from_file_location("tron_arena", APP / "arena.py")
rules = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rules)
Arena = rules.Arena


class ArenaTests(unittest.TestCase):
    def setUp(self):
        self.arena = Arena(76, 44)
        self.arena.choose_cpu = lambda: self.arena.directions[1]

    def positions(self, player, cpu, directions=(rules.RIGHT, rules.LEFT)):
        arena = self.arena
        arena.cells = bytearray(arena.width * arena.height)
        arena.heads = [player, cpu]
        arena.paths = [[player], [cpu]]
        arena.directions = list(directions)
        for rider, (x, y) in enumerate(arena.heads):
            arena.cells[y * arena.width + x] = rider + 1

    def test_reset_clears_all_round_state(self):
        self.arena.turn(rules.UP)
        self.arena.advance(4000)
        self.arena.reset()
        self.assertEqual(self.arena.countdown, 2400)
        self.assertEqual(self.arena.elapsed, 0)
        self.assertEqual(self.arena.steps, 0)
        self.assertIsNone(self.arena.pending)
        self.assertIsNone(self.arena.result)
        self.assertEqual(sum(value != 0 for value in self.arena.cells), 2)

    def test_countdown_and_remainder(self):
        start = self.arena.heads[:]
        self.arena.advance(2399)
        self.assertEqual(self.arena.heads, start)
        self.arena.advance(126)
        self.assertEqual(self.arena.steps, 1)
        self.assertEqual(self.arena.elapsed, 125)

    def test_frame_rate_independent_fixed_steps(self):
        other = Arena(76, 44)
        other.choose_cpu = lambda: other.directions[1]
        self.arena.advance(3600)
        for _ in range(225):
            other.advance(16)
        self.assertEqual(other.cells, self.arena.cells)
        self.assertEqual(other.accumulator, self.arena.accumulator)
        self.assertEqual(other.elapsed, self.arena.elapsed)

    def test_reverse_is_rejected(self):
        self.arena.turn(rules.LEFT)
        self.assertIsNone(self.arena.pending)
        self.arena.step()
        self.assertEqual(self.arena.directions[0], rules.RIGHT)

    def test_first_valid_turn_is_queued_until_next_step(self):
        self.arena.turn(rules.UP)
        self.arena.turn(rules.LEFT)
        self.assertEqual(self.arena.pending, rules.UP)
        self.arena.step()
        self.assertEqual(self.arena.directions[0], rules.UP)
        self.arena.turn(rules.LEFT)
        self.arena.step()
        self.assertEqual(self.arena.directions[0], rules.LEFT)

    def test_all_perpendicular_turns(self):
        for current in range(4):
            for direction in ((current + 1) % 4, (current - 1) % 4):
                with self.subTest(current=current, direction=direction):
                    self.arena.reset()
                    self.arena.directions[0] = current
                    start = self.arena.heads[0]
                    self.arena.turn(direction)
                    self.arena.step()
                    self.assertEqual(self.arena.heads[0], self.arena.target(start, direction))

    def test_trails_remain_solid_and_paths_compress(self):
        start = self.arena.heads[0]
        for _ in range(4):
            self.arena.step()
        self.assertEqual(len(self.arena.paths[0]), 2)
        for x in range(start[0], start[0] + 5):
            self.assertEqual(self.arena.cells[start[1] * self.arena.width + x], 1)
        corner = self.arena.heads[0]
        self.arena.turn(rules.UP)
        self.arena.step()
        self.assertEqual(len(self.arena.paths[0]), 3)
        self.assertEqual(self.arena.paths[0][1], corner)

    def test_each_wall_kills_player(self):
        for position, direction in (
            ((75, 22), rules.RIGHT), ((0, 22), rules.LEFT),
            ((38, 0), rules.UP), ((38, 43), rules.DOWN),
        ):
            with self.subTest(direction=direction):
                self.arena.reset()
                self.positions(position, (60, 30), (direction, rules.LEFT))
                self.arena.step()
                self.assertEqual(self.arena.result, "cpu")

    def test_own_and_enemy_trails_kill_player(self):
        for owner in (1, 2):
            with self.subTest(owner=owner):
                self.arena.reset()
                x, y = self.arena.target(self.arena.heads[0], rules.RIGHT)
                self.arena.cells[y * self.arena.width + x] = owner
                self.arena.step()
                self.assertEqual(self.arena.result, "cpu")

    def test_cpu_crash_awards_player(self):
        self.positions((10, 10), (0, 20))
        self.arena.step()
        self.assertEqual(self.arena.result, "player")

    def test_head_on_collision_is_draw(self):
        self.positions((10, 10), (12, 10))
        self.arena.step()
        self.assertEqual(self.arena.result, "draw")

    def test_swapping_heads_is_draw(self):
        self.positions((10, 10), (11, 10))
        self.arena.step()
        self.assertEqual(self.arena.result, "draw")

    def test_independent_simultaneous_crashes_are_draw(self):
        self.positions((75, 10), (0, 30))
        self.arena.step()
        self.assertEqual(self.arena.result, "draw")

    def test_game_over_does_not_move_or_accept_turns(self):
        self.positions((75, 10), (20, 30))
        self.arena.step()
        snapshot = (self.arena.heads[:], bytes(self.arena.cells), self.arena.steps)
        self.arena.turn(rules.UP)
        self.arena.advance(5000)
        self.arena.step()
        self.assertEqual(snapshot, (self.arena.heads, bytes(self.arena.cells), self.arena.steps))
        self.assertIsNone(self.arena.pending)

    def test_speed_increases_but_is_capped(self):
        self.assertEqual(self.arena.interval, 125)
        self.arena.steps = 120
        self.assertEqual(self.arena.interval, 115)
        self.arena.steps = 100000
        self.assertEqual(self.arena.interval, 80)

    def test_cpu_avoids_blocked_forward_cell(self):
        arena = Arena(76, 44)
        x, y = arena.target(arena.heads[1], rules.LEFT)
        arena.cells[y * arena.width + x] = 1
        direction = arena.choose_cpu()
        self.assertIn(direction, (rules.UP, rules.DOWN))
        self.assertTrue(arena.free(*arena.target(arena.heads[1], direction)))

    def test_cpu_chooses_only_available_exit(self):
        arena = Arena(76, 44)
        for direction in (rules.LEFT, rules.DOWN):
            x, y = arena.target(arena.heads[1], direction)
            arena.cells[y * arena.width + x] = 1
        self.assertEqual(arena.choose_cpu(), rules.UP)

    def test_cpu_prefers_room_over_dead_end(self):
        arena = Arena(20, 14)
        arena.cells = bytearray([1] * (20 * 14))
        arena.heads[1] = (10, 7)
        for x in range(1, 10):
            arena.cells[7 * 20 + x] = 0
        arena.cells[8 * 20 + 10] = 0
        for y in range(9, 14):
            for x in range(1, 19):
                arena.cells[y * 20 + x] = 0
        self.assertEqual(arena.choose_cpu(), rules.DOWN)

    def test_room_search_is_bounded(self):
        self.assertEqual(self.arena.room(10, 10), 96)

    def test_many_ai_rounds_finish_with_valid_grids(self):
        with patch.object(rules.random, "randrange", random.Random(42).randrange):
            for _ in range(20):
                arena = Arena(30, 20)
                for step in range(700):
                    arena.directions.reverse()
                    arena.heads.reverse()
                    direction = arena.choose_cpu()
                    arena.heads.reverse()
                    arena.directions.reverse()
                    arena.turn(direction)
                    arena.step()
                    if arena.result:
                        break
                self.assertIsNotNone(arena.result)
                self.assertTrue(all(value in (0, 1, 2) for value in arena.cells))
                for x, y in arena.heads:
                    self.assertTrue(0 <= x < arena.width and 0 <= y < arena.height)


class FrameLoopTests(unittest.TestCase):
    def setUp(self):
        self.pressed = set()
        self.badge = types.SimpleNamespace(
            ticks_delta=16, mode=Mock(), pressed=lambda button: button in self.pressed,
        )
        self.screen = Mock(width=320, height=240)
        self.screen.measure_text.return_value = (100, 8)
        modules = {
            "os": types.SimpleNamespace(chdir=Mock()),
            "sys": types.SimpleNamespace(path=[]),
            "arena": rules,
        }

        def import_module(name, globals=None, locals=None, fromlist=(), level=0):
            if name in modules:
                return modules[name]
            return builtins.__import__(name, globals, locals, fromlist, level)

        self.scope = {
            "__name__": "tron_under_test",
            "__builtins__": dict(vars(builtins), __import__=import_module),
            "badge": self.badge, "screen": self.screen,
            "font": Mock(), "image": Mock(),
            "color": types.SimpleNamespace(rgb=lambda *channels: channels),
            "HIRES": 1, "VSYNC": 2, "run": Mock(),
        }
        for button in ("UP", "DOWN", "LEFT", "RIGHT", "SELECT", "MENU", "BACK"):
            self.scope["BUTTON_" + button] = button
        source = APP / "__init__.py"
        exec(compile(source.read_text(), str(source), "exec"), self.scope)
        self.arena = self.scope["arena"]
        self.arena.choose_cpu = lambda: self.arena.directions[1]

    def frame(self, *buttons, dt=16):
        self.pressed = set(buttons)
        self.badge.ticks_delta = dt
        self.scope["update"]()

    def test_lifecycle_and_all_screens_render(self):
        self.scope["run"].assert_called_once_with(self.scope["update"])
        self.frame()
        self.assertTrue(any(call.args[0] == "BY kawaigram"
                            for call in self.screen.text.call_args_list))
        self.assertEqual(self.scope["state"], "title")
        self.frame("SELECT")
        self.assertEqual(self.scope["state"], "playing")
        self.frame("MENU")
        self.assertEqual(self.scope["state"], "paused")
        self.frame("BACK")
        self.assertEqual(self.scope["state"], "title")

    def test_pause_freezes_round_and_resume_has_no_catchup(self):
        self.frame("SELECT")
        self.frame("BACK")
        before = (self.arena.countdown, self.arena.steps)
        for _ in range(30):
            self.frame(dt=100)
        self.assertEqual(before, (self.arena.countdown, self.arena.steps))
        self.frame("SELECT")
        self.assertEqual(before, (self.arena.countdown, self.arena.steps))
        self.frame(dt=100)
        self.assertEqual(self.arena.countdown, before[0] - 100)

    def test_countdown_accepts_turns(self):
        self.frame("SELECT")
        self.frame("UP")
        self.assertEqual(self.arena.pending, rules.UP)
        self.assertEqual(self.arena.steps, 0)

    def test_results_score_once_and_restart_is_clean(self):
        for result, score in (("player", [1, 0]), ("cpu", [0, 1]), ("draw", [0, 0])):
            with self.subTest(result=result):
                self.scope["wins"] = [0, 0]
                self.frame("SELECT")
                self.arena.result = result
                self.frame()
                self.assertEqual(self.scope["state"], "over")
                for _ in range(5):
                    self.frame(dt=100)
                self.assertEqual(self.scope["wins"], score)
                self.frame("SELECT")
                self.assertEqual(self.scope["state"], "playing")
                self.assertIsNone(self.arena.result)
                self.assertEqual(self.arena.steps, 0)
                self.assertEqual(sum(value != 0 for value in self.arena.cells), 2)

    def test_result_input_guard(self):
        self.frame("SELECT")
        self.arena.result = "cpu"
        self.frame()
        self.frame("SELECT")
        self.assertEqual(self.scope["state"], "over")
        self.frame("BACK")
        self.assertEqual(self.scope["state"], "title")


if __name__ == "__main__":
    unittest.main()
