"""Two-badge protocol regression tests without radio hardware."""

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "chat_protocol", ROOT / "badge" / "apps" / "attendee_chat" / "chat_protocol.py"
)
protocol = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(protocol)
Chat, Wire = protocol.Chat, protocol.Wire


class Link:
    def __init__(self, peer, capacity=20):
        self.peer = peer
        self.packet_capacity = capacity
        self.ready = True
        self.drop = False

    def capacity(self):
        return self.packet_capacity

    def send(self, packet):
        if not self.ready:
            return False
        if not self.drop:
            message = self.peer.wire.receive(packet)
            if message is not None:
                self.peer.receive(message)
        return True


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.alice = Chat("Alice")
        self.bob = Chat("bob")
        self.ab = Link(self.bob)
        self.ba = Link(self.alice)
        self.alice.start("bob", "1234567890abcdef")
        self.bob.start("", "fedcba0987654321")

    def exchange(self, turns=50, elapsed=20):
        for _ in range(turns):
            self.alice.step(elapsed)
            self.bob.step(elapsed)
            self.alice.wire.flush(self.ab)
            self.bob.wire.flush(self.ba)

    def offer(self):
        self.alice.connected()
        self.bob.connected()
        self.exchange()
        self.assertEqual(self.alice.state, "outgoing")
        self.assertEqual(self.bob.state, "incoming")

    def accept(self):
        self.offer()
        self.bob.accept()
        self.exchange()
        self.assertEqual((self.alice.state, self.bob.state), ("active", "active"))

    def test_handles_and_message_limits(self):
        for valid in ("a", "octo-booth17", "x" * 39, "@Alice"):
            self.assertTrue(protocol.handle(valid))
        for invalid in ("", "-a", "a-", "a--b", "x" * 40, "a b", "a/b", None, {}, 12):
            self.assertFalse(protocol.handle(invalid))
        self.assertTrue(protocol.valid_text("x" * 96))
        for invalid in ("", " ", "x" * 97, "hi\n", "\u263a", None, 7):
            self.assertFalse(protocol.valid_text(invalid))

    def test_self_invite_and_invalid_nonce_are_rejected(self):
        self.assertFalse(self.alice.start("ALICE", "1234567890abcdef"))
        self.assertFalse(self.alice.start("bob", "not-a-session-id"))

    def test_matching_handle_invitation_without_message_leak(self):
        self.offer()
        self.assertEqual(self.bob.peer, "alice")
        self.assertFalse(self.alice.send("t", "not yet"))
        self.assertFalse(self.bob.send("e", 0))
        self.bob.receive(["M", self.bob.session, 1, "t", "unsolicited"])
        self.assertEqual(self.bob.history, [])
        self.alice.receive(["A", "0000000000000000"])
        self.assertEqual(self.alice.state, "outgoing")

    def test_mismatched_target_never_gets_invited(self):
        self.bob.username = "carol"
        self.alice.connected()
        self.bob.connected()
        self.exchange()
        self.assertEqual(self.alice.state, "ended")
        self.assertNotEqual(self.bob.state, "incoming")
        self.assertEqual(self.bob.history, [])

    def test_accept_requires_recipient_action_and_confirmation(self):
        self.offer()
        self.bob.receive(["C", self.bob.session])
        self.assertEqual(self.bob.state, "incoming")
        self.bob.accept()
        self.assertEqual(self.bob.state, "accepting")
        self.assertFalse(self.bob.send("t", "before confirmation"))
        self.exchange()
        self.assertEqual((self.alice.state, self.bob.state), ("active", "active"))

    def test_decline_and_timeout(self):
        self.offer()
        self.bob.decline()
        self.exchange()
        self.assertEqual((self.alice.state, self.bob.state), ("ended", "ended"))
        self.setUp()
        self.offer()
        self.bob.step(protocol.INVITE_MS)
        self.assertEqual(self.bob.state, "ended")
        self.assertIn("timed out", self.bob.status)
        self.assertFalse(self.bob.send("t", "no consent"))

    def test_text_and_all_emojis_both_directions(self):
        self.accept()
        for sender, receiver in ((self.alice, self.bob), (self.bob, self.alice)):
            for kind, value in [("t", "x" * protocol.MAX_TEXT)] + [("e", i) for i in range(6)]:
                self.assertTrue(sender.send(kind, value))
                self.assertFalse(sender.send("t", "wait for ack"))
                self.exchange()
                self.assertIsNone(sender.pending)
                self.assertEqual(sender.history[-1]["status"], "delivered")
                self.assertEqual(receiver.history[-1]["value"], value)

    def test_lost_acceptance_is_retried(self):
        self.offer()
        self.ba.drop = True
        self.bob.accept()
        self.exchange(20)
        self.assertEqual(self.bob.state, "accepting")
        self.ba.drop = False
        self.exchange(200)
        self.assertEqual((self.alice.state, self.bob.state), ("active", "active"))

    def test_duplicate_invitation_does_not_extend_consent_timeout(self):
        self.offer()
        self.bob.step(1000)
        age = self.bob.age
        self.bob.receive(["I", "alice", "bob", self.bob.session])
        self.assertEqual(self.bob.age, age)

    def test_lost_ack_retries_without_duplicate_messages(self):
        self.accept()
        self.ba.drop = True
        self.alice.send("t", "once")
        self.exchange(200)
        self.assertEqual(len(self.bob.history), 1)
        self.assertIsNotNone(self.alice.pending)
        self.ba.drop = False
        self.exchange(200)
        self.assertIsNone(self.alice.pending)
        self.assertEqual(len(self.bob.history), 1)

    def test_unconfirmed_is_not_reported_as_delivered(self):
        self.accept()
        self.ba.drop = True
        self.alice.send("t", "maybe delivered")
        self.exchange(700)
        self.assertEqual(self.alice.history[-1]["status"], "unconfirmed")
        self.assertIn("may have arrived", self.alice.status)
        self.assertIsNone(self.alice.pending)

    def test_backpressure_and_minimum_capacity(self):
        self.ab.ready = False
        self.alice.connected()
        self.alice.wire.flush(self.ab)
        self.assertTrue(self.alice.wire.outbox)
        self.ab.ready = True
        self.bob.connected()
        self.ab.packet_capacity = self.ba.packet_capacity = 5
        self.exchange(300)
        self.bob.accept()
        self.exchange(300)
        self.assertEqual((self.alice.state, self.bob.state), ("active", "active"))

    def test_disconnect_and_reconnect_need_fresh_acceptance(self):
        self.accept()
        old_session = self.alice.session
        self.alice.send("t", "pending")
        self.alice.disconnected()
        self.bob.disconnected()
        self.assertEqual(self.alice.history[-1]["status"], "unconfirmed")
        self.alice.start("bob", "0000000000000001")
        self.bob.start("", "0000000000000002")
        self.offer()
        self.assertEqual(self.alice.history, [])
        self.alice.receive(["A", old_session])
        self.assertFalse(self.alice.send("t", "stale acceptance"))

    def test_close_clears_consent_on_both_sides(self):
        self.accept()
        self.alice.close()
        self.exchange()
        self.assertEqual(self.bob.state, "ended")
        self.assertFalse(self.alice.send("t", "closed"))
        self.assertFalse(self.bob.send("e", 0))

    def test_spoofed_invite_changed_handle_invalid_content(self):
        self.offer()
        self.bob.receive(["I", "carol", "bob", "0000000000000001"])
        self.assertEqual(self.bob.peer, "alice")
        self.bob.accept()
        self.exchange()
        for kind, value in (("t", "\n"), ("e", 6), ("e", True), ("e", -1), ("bad", "text")):
            self.assertFalse(self.alice.send(kind, value))
            self.bob.receive(["M", self.bob.session, 1, kind, value])
        self.assertEqual(self.bob.history, [])
        self.bob.receive(["H", "carol"])
        self.assertEqual(self.bob.state, "ended")

    def test_simultaneous_invites_converge_without_auto_accepting(self):
        self.bob.start("alice", "fedcba0987654321")
        self.offer()
        self.bob.accept()
        self.exchange()
        self.assertEqual((self.alice.state, self.bob.state), ("active", "active"))

    def test_auto_discovery_binds_receiver_and_preserves_consent(self):
        self.alice.start("", "1234567890abcdef", request=True)
        self.assertEqual(self.alice.state, "searching")
        self.assertFalse(self.alice.target)
        self.offer()
        self.assertEqual(self.alice.target, "bob")
        self.assertEqual(self.bob.peer, "alice")
        self.assertFalse(self.alice.send("t", "before consent"))
        self.assertFalse(self.bob.send("e", 0))
        self.bob.receive(["M", self.bob.session, 1, "t", "unsolicited"])
        self.assertEqual(self.bob.history, [])
        self.bob.accept()
        self.exchange()
        self.assertEqual((self.alice.state, self.bob.state), ("active", "active"))
        self.assertIn("accepted", self.alice.status)
        self.alice.send("t", "hello detected receiver")
        self.exchange()
        self.assertEqual(self.alice.history[-1]["status"], "delivered")
        self.assertEqual(self.bob.history[-1]["value"], "hello detected receiver")

    def test_simultaneous_auto_requests_still_require_consent(self):
        self.alice.start("", "1234567890abcdef", request=True)
        self.bob.start("", "fedcba0987654321", request=True)
        self.offer()
        self.assertFalse(self.alice.send("e", 0))
        self.bob.accept()
        self.exchange()
        self.assertEqual((self.alice.state, self.bob.state), ("active", "active"))

    def test_two_receivers_never_invite_or_auto_accept(self):
        self.alice.start("", "1234567890abcdef")
        self.alice.connected()
        self.bob.connected()
        self.exchange()
        self.assertEqual((self.alice.state, self.bob.state), ("connecting", "connecting"))
        self.assertFalse(self.alice.send("t", "not a request"))
        self.assertFalse(self.bob.send("e", 0))
        self.exchange(turns=1600)
        self.assertEqual((self.alice.state, self.bob.state), ("ended", "ended"))

    def test_device_ids_can_chat_without_github_handles(self):
        self.alice.username = "badge-1234567890abcdef"
        self.bob.username = "badge-fedcba0987654321"
        self.alice.start("", "1234567890abcdef", request=True)
        self.bob.start("", "fedcba0987654321")
        self.accept()
        self.alice.send("e", 5)
        self.exchange()
        self.assertEqual(self.bob.history[-1]["value"], 5)

    def test_history_is_bounded_and_sequence_replays_are_deduplicated(self):
        self.accept()
        for i in range(40):
            self.alice.send("t", "Message " + str(i))
            self.exchange()
        self.assertEqual(len(self.alice.history), protocol.HISTORY_LIMIT)
        self.assertEqual(len(self.bob.history), protocol.HISTORY_LIMIT)
        self.bob.receive(["M", self.bob.session, 1, "t", "replay"])
        self.assertEqual(self.bob.history[-1]["value"], "Message 39")


class WireTests(unittest.TestCase):
    def test_rejects_bad_frames_and_json(self):
        for packet in (b"", b"C", b"C\x00\x00x", b"C\x01\x01x",
                       b"C\x01\x02x", b"X\x00\x01x", b"C\x00\x01{}",
                       b"C\x00\x01[0]", b"C\x00\x01\xff"):
            with self.subTest(packet=packet):
                with self.assertRaises(ValueError):
                    Wire().receive(packet)

    def test_queue_and_reassembly_are_bounded(self):
        wire = Wire()
        for index in range(8):
            wire.queue(["H", str(index)])
        with self.assertRaises(ValueError):
            wire.queue(["H", "overflow"])
        with self.assertRaises(ValueError):
            Wire().queue(["M", "x" * 400])
        with self.assertRaises(ValueError):
            Wire().receive(b"C\x00\x01" + b"x" * 385)


if __name__ == "__main__":
    unittest.main()
