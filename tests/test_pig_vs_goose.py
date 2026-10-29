"""Host-side regression tests for Pig vs Goose's physics and turn rules."""

import importlib.util
from pathlib import Path
import random
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "badge/apps/pig_vs_goose/game.py"
SPEC = importlib.util.spec_from_file_location("pig_goose_physics", SOURCE)
physics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(physics)


class PigGooseTests(unittest.TestCase):
    def setUp(self):
        random.seed(23)
        self.game = physics.Game()

    def flat(self, top=75):
        for y, row in enumerate(self.game.terrain):
            row[:] = bytes([int(top <= y < physics.FLOOR)]) * physics.WIDTH
        for p in self.game.players:
            p.update(y=float(top), fall=float(top), vy=0.0, vx=0.0,
                     tilt=0.0, wheel=0.0, soak=0)
        self.game.butterfly_delay = 10000

    def remove_support(self, player):
        x = int(player["x"])
        for row in self.game.terrain:
            row[max(0, x - 6):x + 7] = bytes(13)

    def advance_until(self, predicate, limit=5000, dt=1 / 60):
        for _ in range(limit):
            if predicate():
                return
            self.game.update(dt)
        self.fail("Game did not reach expected state: " + self.game.phase)

    def test_initial_support_and_turn(self):
        self.assertEqual(self.game.phase, "move")
        self.assertTrue(all(self.game.supported(p) for p in self.game.players))
        self.assertEqual(self.game.active, 0)

    def test_circular_crater_preserves_pixels_outside_circle(self):
        self.flat(40)
        before = [bytes(row) for row in self.game.terrain]
        self.game.explode(80, 65)
        removed = 0
        for y in range(physics.HEIGHT):
            for x in range(physics.WIDTH):
                inside = (x - 80) ** 2 + (y - 65) ** 2 <= physics.BLAST_RADIUS ** 2
                expected = 0 if inside else before[y][x]
                self.assertEqual(self.game.terrain[y][x], expected)
                removed += before[y][x] - self.game.terrain[y][x]
        self.assertGreater(removed, 850)
        self.assertEqual(self.game.revision, 1)

    def test_splash_fall_damage_and_turn_handoff(self):
        self.flat(60)
        p = self.game.players[0]
        self.game.explode(p["x"], p["y"])
        immediate_soak = p["soak"]
        self.advance_until(lambda: self.game.active == 1)
        self.assertGreater(p["y"], 60)
        self.assertGreaterEqual(p["soak"], immediate_soak)
        self.assertEqual(self.game.phase, "think")

    def test_falling_into_water_finishes_round(self):
        self.flat()
        self.remove_support(self.game.players[0])
        self.game.phase = "settle"
        self.advance_until(lambda: self.game.phase == "over")
        self.assertEqual(self.game.players[0]["soak"], 100)
        self.assertEqual(self.game.winner, 1)
        self.assertEqual(self.game.result_lines(),
                         ("PIG reached 100% soaked", "Cause: fell into water"))

    def test_both_falling_into_water_is_draw(self):
        self.flat()
        for p in self.game.players:
            self.remove_support(p)
        self.game.phase = "settle"
        self.advance_until(lambda: self.game.phase == "over")
        self.assertEqual(self.game.winner, -1)
        self.assertEqual(self.game.result_lines(),
                         ("PIG: fell into water", "GOOSE: fell into water"))

    def test_lethal_splash_explains_loss_above_water(self):
        self.flat(60)
        p = self.game.players[0]
        p["soak"] = 90
        self.game.explode(p["x"], p["y"] - 4)
        self.advance_until(lambda: self.game.phase == "over")
        self.assertLess(p["y"], physics.FLOOR)
        self.assertEqual(self.game.result_lines(),
                         ("PIG reached 100% soaked", "Cause: balloon splash"))

    def test_lethal_landing_explains_loss_above_water(self):
        self.flat(85)
        p = self.game.players[0]
        p.update(y=60.0, fall=60.0, soak=90)
        self.advance_until(lambda: self.game.phase == "over")
        self.assertLess(p["y"], physics.FLOOR)
        self.assertEqual(self.game.result_lines(),
                         ("PIG reached 100% soaked", "Cause: hard landing"))

    def test_lethal_cause_is_not_overwritten(self):
        p = self.game.players[0]
        self.game.add_soak(p, 100, "splash")
        self.game.add_soak(p, 10, "fall")
        self.assertEqual(p["cause"], "splash")

    def test_zero_damage_does_not_change_cause(self):
        p = self.game.players[0]
        self.game.add_soak(p, 10, "fall")
        self.game.add_soak(p, 0, "splash")
        self.assertEqual(p["cause"], "fall")

    def test_damage_is_radial_and_can_hit_thrower(self):
        self.flat()
        self.game.explode(24, 70)
        self.assertGreater(self.game.players[0]["soak"], 40)
        self.assertEqual(self.game.players[1]["soak"], 0)

    def test_walk_budget_survives_aim_toggle(self):
        self.flat()
        for _ in range(100):
            self.game.move(0.25)
        self.assertAlmostEqual(self.game.players[0]["x"], 36, places=5)
        self.assertAlmostEqual(self.game.walk, 0, places=5)
        self.game.aim()
        self.game.phase = "move"
        self.game.move(10)
        self.assertAlmostEqual(self.game.players[0]["x"], 36, places=5)

    def test_walk_does_not_skip_tall_obstacles(self):
        self.flat()
        for y in range(60, 75):
            self.game.terrain[y][28] = 1
        self.game.move(12)
        self.assertLess(self.game.players[0]["x"], 28)
        self.assertGreater(self.game.walk, 7)

    def test_ballistics_mirror_without_wind(self):
        self.flat()
        self.game.wind = 0
        left = self.game.launch_values(47, 66, 0)
        right = self.game.launch_values(47, 66, 1)
        for _ in range(100):
            self.game.advance_ball(left, physics.STEP)
            self.game.advance_ball(right, physics.STEP)
        self.assertAlmostEqual(left[0] + right[0], physics.WIDTH)
        self.assertAlmostEqual(left[1], right[1])

    def test_fixed_step_flight_is_frame_rate_independent(self):
        self.flat()
        self.game.wind = 2
        self.game.aim()
        self.game.fire()
        other = physics.Game()
        other.wind = self.game.wind
        other.terrain = [bytearray(row) for row in self.game.terrain]
        other.players = [dict(p) for p in self.game.players]
        other.aim()
        other.fire()
        for _ in range(30):
            self.game.update(1 / 30)
        for _ in range(120):
            other.update(1 / 120)
        for a, b in zip(self.game.projectile, other.projectile):
            self.assertAlmostEqual(a, b)

    def test_miss_advances_without_terrain_damage(self):
        self.flat()
        self.game.players[0]["angle"] = 170
        self.game.players[0]["power"] = 100
        self.game.aim()
        self.game.fire()
        self.advance_until(lambda: self.game.active == 1)
        self.assertEqual(self.game.revision, 0)

    def test_computer_search_fires_and_lands_near_target(self):
        self.flat()
        self.game.finish_turn()
        self.assertEqual(self.game.phase, "think")
        self.advance_until(lambda: self.game.phase == "flight")
        score, angle, power = self.game.ai_best
        self.assertLess(score, 16)
        self.assertTrue(10 <= angle <= 170)
        self.assertTrue(20 <= power <= 100)
        self.advance_until(lambda: self.game.phase != "flight")

    def test_pass_and_play_handoff(self):
        self.game.computer = False
        self.game.finish_turn()
        self.assertEqual((self.game.active, self.game.phase), (1, "move"))
        self.game.finish_turn()
        self.assertEqual((self.game.active, self.game.phase), (0, "move"))
        self.assertEqual(self.game.walk, physics.WALK_DISTANCE)

    def test_full_duel_terminates(self):
        self.flat(85)
        for turn in range(80):
            if self.game.phase == "over":
                break
            if self.game.phase == "move":
                self.game.aim()
                p = self.game.players[self.game.active]
                choices = [(self.game.evaluate_shot(a, power), a, power)
                           for a in range(25, 86, 10) for power in range(35, 101, 10)]
                _, p["angle"], p["power"] = min(choices)
                self.game.fire()
            self.advance_until(lambda: self.game.phase in ("move", "over"))
        self.assertEqual(self.game.phase, "over")

    def test_soak_bar_gradient(self):
        self.assertEqual(physics.soak_rgb(0), (45, 154, 216))
        self.assertEqual(physics.soak_rgb(100), (235, 55, 55))
        self.assertEqual(physics.soak_rgb(-10), physics.soak_rgb(0))
        self.assertEqual(physics.soak_rgb(110), physics.soak_rgb(100))
        yellow = physics.soak_rgb(34)
        orange = physics.soak_rgb(68)
        self.assertGreater(yellow[0], 240)
        self.assertGreater(yellow[1], 210)
        self.assertLess(yellow[2], 80)
        self.assertGreater(orange[0], 240)
        self.assertLess(orange[1], yellow[1])
        self.assertNotEqual(physics.soak_rgb(40), physics.soak_rgb(50))

    def test_butterfly_flight_randomization_and_sine_wave(self):
        directions, bases, amplitudes = set(), [], []
        for _ in range(40):
            self.game.spawn_butterfly()
            b = self.game.butterfly
            directions.add(b["direction"])
            bases.append(b["base"])
            amplitudes.append(b["amplitude"])
            before_x = b["x"]
            self.game.update_butterfly(0.1)
            self.assertAlmostEqual(b["x"], before_x + b["direction"] * b["speed"] * 0.1)
            self.assertAlmostEqual(b["y"], b["base"] + b["amplitude"] *
                                   physics.math.sin(b["phase"] + 0.1 * b["frequency"]))
            self.assertGreaterEqual(b["base"] - b["amplitude"], 22)
            self.assertLessEqual(b["base"] + b["amplitude"], 43)
        self.assertEqual(directions, {-1, 1})
        self.assertGreater(max(bases) - min(bases), 6)
        self.assertGreater(max(amplitudes) - min(amplitudes), 3)

    def test_butterfly_spawn_and_exit_cooldown(self):
        self.game.butterfly_delay = 0.01
        self.game.update_butterfly(0.02)
        self.assertIsNotNone(self.game.butterfly)
        self.game.butterfly["x"] = physics.WIDTH + 20
        self.game.update_butterfly(0.01)
        self.assertIsNone(self.game.butterfly)
        self.assertTrue(9 <= self.game.butterfly_delay <= 17)

    def test_balloon_hit_butterfly_starts_dryer_without_crater(self):
        self.flat()
        self.game.players[0]["soak"] = 70
        self.game.spawn_butterfly()
        self.game.butterfly.update(x=80.0, y=35.0, base=35.0, amplitude=0, speed=0)
        self.game.phase = "flight"
        self.game.projectile = [80.0, 35.0, 0.0, 0.0, 1.0]
        self.game.update(physics.STEP)
        self.assertEqual(self.game.phase, "dryer")
        self.assertIsNone(self.game.butterfly)
        self.assertIsNone(self.game.projectile)
        self.assertEqual(self.game.revision, 0)
        self.assertEqual(self.game.players[0]["soak"], 70)
        self.advance_until(lambda: self.game.dryer_applied)
        self.assertEqual(self.game.players[0]["soak"], 45)
        self.assertEqual(self.game.players[1]["soak"], 0)
        self.advance_until(lambda: self.game.phase == "think")
        self.assertEqual(self.game.active, 1)

    def test_dryer_never_negative_and_applies_only_once(self):
        self.flat()
        self.game.players[0]["soak"] = 10
        self.game.start_dryer()
        self.advance_until(lambda: self.game.dryer_applied)
        self.assertEqual(self.game.players[0]["soak"], 0)
        self.game.players[0]["soak"] = 12
        for _ in range(20):
            self.game.update(1 / 60)
        self.assertEqual(self.game.players[0]["soak"], 12)

    def test_dryer_targets_goose_on_goose_turn_and_freezes_carts(self):
        self.flat()
        self.game.active = 1
        self.game.players[0]["soak"] = 70
        self.game.players[1]["soak"] = 80
        self.game.players[0]["vx"] = 12
        x = self.game.players[0]["x"]
        self.game.start_dryer()
        self.advance_until(lambda: self.game.dryer_applied)
        self.assertEqual(self.game.players[0]["soak"], 70)
        self.assertEqual(self.game.players[1]["soak"], 55)
        self.assertEqual(self.game.players[0]["x"], x)

    def slope(self):
        for y, row in enumerate(self.game.terrain):
            for x in range(physics.WIDTH):
                top = 60 + x // 2 if x < 60 else 90
                row[x] = int(top <= y < physics.FLOOR)
        p = self.game.players[0]
        p["y"], p["tilt"] = self.game.ground_pose(p["x"], 72)
        p["fall"] = p["y"]
        self.game.players[1].update(y=90.0, fall=90.0)

    def test_carts_roll_to_basin_and_align_to_slope(self):
        self.flat()
        self.slope()
        p = self.game.players[0]
        self.assertGreater(p["tilt"], 0.3)
        self.assertLess(p["tilt"], 0.6)
        old_x = p["x"]
        for _ in range(60):
            self.game.update(1 / 60)
        self.assertGreater(p["x"], old_x + 3)
        self.assertGreater(p["wheel"], 1)
        for _ in range(900):
            self.game.update(1 / 60)
        self.assertGreater(p["x"], 60)
        self.assertTrue(self.game.carts_still())
        self.assertAlmostEqual(p["tilt"], 0)

    def test_cart_roll_is_frame_rate_independent(self):
        self.flat()
        self.slope()
        other = physics.Game()
        other.terrain = [bytearray(row) for row in self.game.terrain]
        other.players = [dict(p) for p in self.game.players]
        other.butterfly_delay = 10000
        for _ in range(120):
            self.game.update(1 / 30)
        for _ in range(480):
            other.update(1 / 120)
        for key in ("x", "y", "vx", "vy", "tilt"):
            self.assertAlmostEqual(self.game.players[0][key], other.players[0][key])

    def test_cart_rolling_into_water_cannot_stall_turn(self):
        self.flat(physics.FLOOR - 1)
        p = self.game.players[0]
        for row in self.game.terrain:
            row[30:80] = bytes(50)
        p["vx"] = 20
        self.advance_until(lambda: self.game.phase == "over")
        self.assertEqual(p["soak"], 100)
        self.assertEqual(p["cause"], "water")
        self.assertEqual(p["y"], physics.FLOOR)

    def test_wheel_contacts_match_ramp(self):
        self.flat()
        self.slope()
        p = self.game.players[0]
        half = physics.WHEEL_BASE / 2
        for direction in (-1, 1):
            x = p["x"] + direction * half * physics.math.cos(p["tilt"])
            y = p["y"] + direction * half * physics.math.sin(p["tilt"])
            self.assertLessEqual(abs(y - self.game.surface(x)), 1.1)

    def test_firing_waits_for_rolling_carts(self):
        self.flat()
        self.slope()
        self.game.update(0.05)
        self.game.aim()
        self.assertEqual(self.game.phase, "move")
        self.game.phase = "aim"
        self.game.fire()
        self.assertIsNone(self.game.projectile)

    def test_generated_terrain_has_waves_and_cliff(self):
        for seed in range(20):
            random.seed(seed)
            game = physics.Game()
            tops = [game.surface(x) for x in range(physics.WIDTH)]
            self.assertGreater(max(tops) - min(tops), 32)
            self.assertGreaterEqual(abs(tops[game.cliff] - tops[game.cliff - 1]), 14)
            slopes = [tops[x] - tops[x - 1] for x in range(1, physics.WIDTH)
                      if tops[x] != tops[x - 1]]
            turns = sum(a * b < 0 for a, b in zip(slopes, slopes[1:]))
            self.assertGreaterEqual(turns, 5)

    def test_rugged_landscapes_allow_complete_duels(self):
        for seed in range(20):
            with self.subTest(seed=seed):
                random.seed(seed)
                self.game = physics.Game()
                self.game.butterfly_delay = 10000
                for _ in range(120):
                    self.game.update(1 / 60)
                self.advance_until(lambda: self.game.carts_still())
                for _ in range(60):
                    if self.game.phase == "over":
                        break
                    if self.game.phase == "move":
                        self.game.aim()
                        p = self.game.players[self.game.active]
                        choices = [(self.game.evaluate_shot(a, power), a, power)
                                   for a in range(20, 86, 10)
                                   for power in range(30, 101, 10)]
                        _, p["angle"], p["power"] = min(choices)
                        self.game.fire()
                    self.advance_until(lambda: self.game.phase in ("move", "over")
                                       and self.game.carts_still())
                self.assertEqual(self.game.phase, "over")


if __name__ == "__main__":
    unittest.main()
