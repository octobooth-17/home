"""Paired-link regression tests, without a radio or simulator shim."""

import importlib.util
import json
from pathlib import Path
import random
import struct
import sys
import unittest
from unittest.mock import patch


APP = Path(__file__).resolve().parents[1] / "badge/apps/pig_vs_goose"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, APP / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


game_module = load("linked_game_physics", "game.py")
with patch.dict(sys.modules, {"game": game_module}):
    multiplayer = load("pig_goose_multiplayer", "multiplayer.py")


class FakeLink:
    def __init__(self, central, capacity=64):
        self.central = central
        self.linked = True
        self.messages = []
        self.peer = None
        self.limit = capacity
        self.drop_kind = None
        self.drop_count = 0
        self.blocked = False
        self.duplicate = False
        self.closed = False
        self.sent = []

    def capacity(self):
        return self.limit

    def pump(self):
        pass

    def update(self):
        pass

    def receive(self):
        messages, self.messages = self.messages, []
        return messages

    def send(self, message):
        if self.blocked:
            return False
        assert len(message) <= self.limit
        self.sent.append(message)
        if message[:1] == self.drop_kind and self.drop_count:
            self.drop_count -= 1
            return True
        self.peer.messages.append(message)
        if self.duplicate:
            self.peer.messages.append(message)
        return True

    def leave(self):
        self.linked = False

    def close(self):
        self.closed = True
        self.linked = False


class Proximity:
    def __init__(self):
        self.searches = 0

    def update(self, now):
        self.searches += 1


class MultiplayerTests(unittest.TestCase):
    def setUp(self):
        random.seed(9)
        self.links = [FakeLink(True), FakeLink(False)]
        self.links[0].peer = self.links[1]
        self.links[1].peer = self.links[0]
        self.host = multiplayer.Multiplayer(self.links[0], Proximity())
        self.guest = multiplayer.Multiplayer(self.links[1], Proximity())
        self.now = 0

    def tick(self, host_buttons=0, guest_buttons=0, guest_axes=(0, 0), dt=1 / 60):
        self.now += dt
        self.host.update(int(self.now * 1000), dt, buttons=host_buttons)
        self.guest.update(int(self.now * 1000), dt, *guest_axes, guest_buttons)
        self.assertNotEqual(self.host.status, "error", self.host.message)
        self.assertNotEqual(self.guest.status, "error", self.guest.message)

    def until(self, condition, limit=3000):
        for _ in range(limit):
            if condition():
                return
            self.tick()
        self.fail("Timeout: host=%s guest=%s" % (self.host.status, self.guest.status))

    def pair(self):
        self.tick()
        self.tick(multiplayer.SELECT, multiplayer.SELECT)
        self.until(lambda: self.guest.status == "play")

    def flatten(self):
        for y, row in enumerate(self.host.game.terrain):
            row[:] = bytes([int(85 <= y < game_module.FLOOR)]) * game_module.WIDTH
        for p in self.host.game.players:
            p.update(y=85.0, fall=85.0, vx=0.0, vy=0.0, tilt=0.0, soak=0)
        self.host.game.initial_surface = [85] * game_module.WIDTH
        self.host.game.craters = []
        self.host.game.revision += 1
        self.host.game.butterfly_delay = 10000

    def test_pairing_requires_both_accepts_and_assigns_roles(self):
        self.tick()
        self.tick(host_buttons=multiplayer.SELECT)
        for _ in range(80):
            self.tick()
        self.assertIsNone(self.host.game)
        self.assertIsNone(self.guest.game)
        self.tick(guest_buttons=multiplayer.SELECT)
        self.until(lambda: self.guest.status == "play")
        self.assertEqual(self.host.local_player, 0)
        self.assertEqual(self.guest.local_player, 1)
        self.assertFalse(self.host.game.computer)
        self.assertEqual(self.guest.game.terrain, self.host.game.terrain)

    def test_snapshot_roundtrip_includes_terrain_craters_and_bonus(self):
        self.pair()
        self.flatten()
        game = self.host.game
        game.explode(100, 84)
        game.spawn_butterfly()
        game.players[0]["soak"] = 70
        game.start_dryer()
        game.update_dryer(1.7)
        self.guest.apply_snapshot(self.host.snapshot())
        self.assertEqual(self.guest.game.terrain, game.terrain)
        for key in multiplayer.STATE_KEYS:
            expected = json.loads(json.dumps(getattr(game, key)))
            self.assertEqual(getattr(self.guest.game, key), expected, key)
        self.assertEqual(self.guest.game.players, game.players)

    def test_dropped_snapshot_fragments_and_ack_are_retried(self):
        self.links[0].drop_kind = b"S"
        self.links[0].drop_count = 5
        self.links[1].drop_kind = b"K"
        self.links[1].drop_count = 1
        self.pair()
        self.until(lambda: self.host.terrain_acked == (self.host.round, self.host.game.revision))
        self.assertEqual(self.host.game.terrain, self.guest.game.terrain)
        self.assertEqual(self.links[0].drop_count, 0)

    def test_send_backpressure_and_duplicate_packets(self):
        self.links[0].blocked = True
        self.tick()
        self.tick(multiplayer.SELECT, multiplayer.SELECT)
        for _ in range(20):
            self.tick()
        self.links[0].blocked = False
        self.links[0].duplicate = self.links[1].duplicate = True
        self.until(lambda: self.guest.status == "play")
        self.assertEqual(self.guest.round, 1)

    def test_small_capacity_link_handles_fragmentation(self):
        self.links[0].limit = self.links[1].limit = 20
        self.pair()
        self.until(lambda: self.host.terrain_acked is not None)
        self.assertEqual(self.host.game.terrain, self.guest.game.terrain)
        self.assertTrue(all(len(packet) <= 20 for link in self.links for packet in link.sent))

    def test_missing_game_ack_times_out_even_with_heartbeats(self):
        self.links[1].drop_kind = b"K"
        self.links[1].drop_count = 10000
        self.pair()
        for _ in range(900):
            self.now += 1 / 60
            self.host.update(int(self.now * 1000), 1 / 60)
            self.guest.update(int(self.now * 1000), 1 / 60)
            if self.host.status == "error":
                break
        self.assertEqual(self.host.status, "error")
        self.assertIn("Game sync timed out", self.host.message)

    def test_fragment_reordering_reassembles_one_snapshot(self):
        self.pair()
        self.host.outgoing = None
        self.host.queue_snapshot()
        for fragment in reversed(self.host.outgoing):
            self.guest.receive_snapshot(fragment)
        self.assertEqual(self.guest.received_sequence, self.host.sequence)
        self.assertEqual(self.guest.game.terrain, self.host.game.terrain)

    def test_remote_axes_only_control_goose_on_goose_turn(self):
        self.pair()
        self.flatten()
        pig_x = self.host.game.players[0]["x"]
        for _ in range(60):
            self.tick(guest_axes=(1, 0))
        self.assertEqual(self.host.game.players[0]["x"], pig_x)
        self.host.game.finish_turn()
        self.until(lambda: self.guest.game.active == 1)
        x = self.host.game.players[1]["x"]
        for _ in range(60):
            self.tick(guest_axes=(-1, 0))
        self.assertLess(self.host.game.players[1]["x"], x - 5)
        self.assertEqual(self.host.game.players[0]["x"], pig_x)

    def test_duplicate_select_never_aims_and_fires_twice(self):
        self.pair()
        self.flatten()
        self.host.game.finish_turn()
        self.until(lambda: self.guest.game.active == 1)
        self.links[1].duplicate = True
        self.links[0].drop_kind = b"J"
        self.links[0].drop_count = 2
        self.tick(guest_buttons=multiplayer.SELECT)
        self.until(lambda: self.host.game.phase == "aim")
        for _ in range(90):
            self.tick()
        self.assertEqual(self.host.game.phase, "aim")
        self.assertIsNone(self.host.game.projectile)

    def test_stale_turn_and_phase_commands_ignored(self):
        self.pair()
        self.flatten()
        self.host.game.finish_turn()
        game = self.host.game
        stale = b"I" + struct.pack("<IIIBbbB", 15, self.host.round, game.turn - 1,
                                   0, 1, 0, multiplayer.SELECT)
        self.host.receive_input(stale)
        self.assertEqual(game.phase, "move")
        stale = b"I" + struct.pack("<IIIBbbB", 16, self.host.round, game.turn,
                                   1, 1, 0, multiplayer.SELECT)
        self.host.receive_input(stale)
        self.assertEqual(game.phase, "move")

    def test_remote_held_input_lease_expires(self):
        self.pair()
        self.flatten()
        self.host.game.finish_turn()
        game = self.host.game
        packet = b"I" + struct.pack("<IIIBbbB", 20, self.host.round, game.turn, 0, -1, 0, 0)
        self.host.receive_input(packet)
        for _ in range(120):
            self.now += 1 / 60
            self.host.update(int(self.now * 1000), 1 / 60)
        self.assertGreater(game.walk, 7)
        self.assertLess(game.walk, 12)

    def test_pause_resume_from_either_badge_freezes_dryer(self):
        self.pair()
        self.flatten()
        self.host.game.players[0]["soak"] = 70
        self.host.game.start_dryer()
        self.until(lambda: self.guest.game.phase == "dryer")
        self.tick(guest_buttons=multiplayer.MENU)
        self.until(lambda: self.host.paused and self.guest.paused)
        frozen = self.host.game.dryer_time
        for _ in range(100):
            self.tick()
        self.assertEqual(self.host.game.dryer_time, frozen)
        self.tick(host_buttons=multiplayer.SELECT)
        self.until(lambda: not self.guest.paused)
        self.until(lambda: self.host.game.dryer_applied)
        self.until(lambda: self.guest.game.dryer_applied)
        self.assertEqual(self.guest.game.players[0]["soak"], 45)

    def test_rematch_requires_both_votes_and_new_landscape(self):
        self.pair()
        self.flatten()
        self.host.game.add_soak(self.host.game.players[0], 100, "splash")
        self.until(lambda: self.guest.game.phase == "over")
        self.tick(host_buttons=multiplayer.SELECT)
        for _ in range(30):
            self.tick()
        self.assertEqual(self.host.round, 1)
        self.tick(guest_buttons=multiplayer.SELECT)
        self.until(lambda: self.guest.round == 2)
        self.assertEqual(self.host.round, 2)
        self.assertEqual(self.guest.game.terrain, self.host.game.terrain)
        self.assertEqual(self.guest.game.revision, 0)

    def test_disconnect_and_silence_visible(self):
        self.pair()
        self.links[0].linked = False
        self.host.update(1000, 0.1)
        self.assertEqual(self.host.status, "error")
        self.assertIn("Connection lost", self.host.message)
        self.guest.heard_at = self.guest.time - multiplayer.TIMEOUT - 1
        self.links[1].messages = []
        self.guest.update(1000, 0.1)
        self.assertEqual(self.guest.status, "error")
        self.assertIn("stopped responding", self.guest.message)

    def test_version_mismatch_and_invalid_packets_report_errors(self):
        self.host.handle(b"Aold-version")
        self.assertEqual(self.host.status, "error")
        self.assertIn("Different game versions", self.host.message)
        self.guest.receive_snapshot(b"S" + struct.pack("<IHH", 1, 10, 2) + b"x")
        self.assertEqual(self.guest.status, "error")

    def test_roundtrip_preserves_overhangs(self):
        self.pair()
        self.flatten()
        self.host.game.explode(100, 111)
        self.guest.apply_snapshot(self.host.snapshot())
        self.assertTrue(self.guest.game.solid(100, 87))
        self.assertFalse(self.guest.game.solid(100, 111))
        self.assertEqual(self.guest.game.terrain, self.host.game.terrain)


if __name__ == "__main__":
    unittest.main()
