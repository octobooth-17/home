"""Exercise app controls and the offline peer using the runtime's public API."""

import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, mock_open, patch


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "badge" / "apps" / "attendee_chat"


def load(name):
    spec = importlib.util.spec_from_file_location(name, APP / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UITests(unittest.TestCase):
    def setUp(self):
        self.protocol = load("chat_protocol")
        self.pressed = set()
        self.clock = types.SimpleNamespace(
            ticks=0, ticks_delta=20, mode=Mock(),
            pressed=lambda key: key in self.pressed,
        )
        self.screen = Mock(width=320, height=240)
        self.screen.measure_text.side_effect = lambda value: (len(value) * 6, 8)
        self.secrets = types.SimpleNamespace(GITHUB_USERNAME="alice")
        self.badgelink = Mock()
        self.run = Mock()
        self.modules = {
            "os": types.SimpleNamespace(chdir=Mock(), urandom=lambda n: b"\x17" * n, stat=os.stat),
            "sys": types.SimpleNamespace(path=[], platform="rp2"),
            "badgeware": types.SimpleNamespace(link=self.badgelink),
            "secrets": self.secrets,
            "machine": types.SimpleNamespace(unique_id=lambda: b"\x17" * 8),
            "chat_protocol": self.protocol,
        }
        with patch.dict(sys.modules, {"chat_protocol": self.protocol}):
            self.modules["chat_demo"] = load("chat_demo")
        self.modules["usb_relay"] = load("usb_relay")
        self.namespace = {
            "__name__": "attendee_chat_test",
            "badge": self.clock, "screen": self.screen, "image": Mock(),
            "color": Mock(), "font": Mock(), "vec2": lambda x, y: (x, y),
            "HIRES": 1, "VSYNC": 2, "run": self.run,
        }
        for key in ("LEFT", "RIGHT", "UP", "DOWN", "SELECT", "MENU", "BACK"):
            self.namespace["BUTTON_" + key] = key
        self.module_patch = patch.dict(sys.modules, self.modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.load_app()

    def load_app(self):
        exec(compile((APP / "__init__.py").read_text(), str(APP / "__init__.py"), "exec"),
             self.namespace)
        self.app = self.namespace["app"]

    def tick(self, key=None, frames=1):
        for _ in range(frames):
            self.pressed.clear()
            if key is not None:
                self.pressed.add(key)
            self.clock.ticks += self.clock.ticks_delta
            self.app.update()
            self.app.draw()
        self.pressed.clear()

    def demo(self):
        self.app.selection = 3
        self.tick("SELECT")
        self.tick(frames=80)
        self.assertEqual(self.app.view, "offer")
        self.tick("SELECT")
        self.tick(frames=100)
        self.assertEqual(self.app.view, "chat")

    def test_initialization_and_demo_never_open_radio(self):
        self.badgelink.Link.assert_not_called()
        self.demo()
        self.badgelink.Link.assert_not_called()
        labels = [call.args[0] for call in self.screen.text.call_args_list]
        self.assertIn("DEMO / NO RADIO", labels)
        self.assertTrue(any("Offline demo!" in entry["value"]
                            for entry in self.app.chat.history if entry["kind"] == "t"))

    def test_text_keyboard_send_delivery_and_echo(self):
        self.demo()
        self.tick("SELECT")
        self.assertEqual(self.app.view, "keyboard")
        self.app.keyboard.value = "Hello, Universe!"
        self.app.keyboard.cursor = self.app.keyboard.keys().index("Send")
        self.tick("SELECT")
        self.tick(frames=100)
        outgoing = [entry for entry in self.app.chat.history if entry["mine"]]
        self.assertEqual(outgoing[-1]["status"], "delivered")
        self.assertEqual(self.app.chat.history[-1]["value"], "Demo echo: Hello, Universe!")

    def test_six_emoji_picker_and_echo(self):
        self.demo()
        for index in range(6):
            self.tick("MENU")
            self.assertEqual(self.app.view, "emoji")
            self.app.emoji = index
            self.tick("SELECT")
            self.tick(frames=100)
            self.assertEqual(self.app.chat.history[-1]["kind"], "e")
            self.assertEqual(self.app.chat.history[-1]["value"], index)
            self.assertFalse(self.app.chat.history[-1]["mine"])

    def test_emoji_and_close_work_with_only_arrows_and_select(self):
        self.demo()
        self.tick("SELECT")
        keyboard = self.app.keyboard
        keyboard.cursor = keyboard.keys().index("Close")
        self.tick("SELECT")
        self.assertEqual(self.app.view, "chat")
        self.tick("SELECT")
        self.app.keyboard.cursor = self.app.keyboard.keys().index("Emoji")
        self.tick("SELECT")
        self.assertEqual(self.app.view, "emoji")
        self.tick("RIGHT")
        self.tick("SELECT")
        self.tick(frames=100)
        self.assertEqual(self.app.view, "chat")
        self.assertIn(("e", 1), [(e["kind"], e["value"]) for e in self.app.chat.history])

    def test_decline_end_confirmation_and_return_home(self):
        self.app.start_demo()
        self.tick(frames=80)
        self.tick("BACK")
        self.assertEqual(self.app.view, "result")
        self.tick("SELECT")
        self.assertEqual(self.app.view, "home")
        self.assertIsNone(self.app.demo)
        self.demo()
        self.tick("BACK")
        self.assertEqual(self.app.view, "leave")
        self.tick("BACK")
        self.assertEqual(self.app.view, "chat")
        self.tick("BACK")
        self.tick("SELECT")
        self.assertEqual(self.app.view, "result")
        self.tick("SELECT")
        self.assertEqual(self.app.chat.history, [])
        self.assertIsNone(self.app.demo)

    def test_cancelled_draft_and_scroll(self):
        self.demo()
        self.tick("SELECT")
        self.app.keyboard.value = "Unsent draft"
        self.tick("BACK")
        self.tick("SELECT")
        self.assertEqual(self.app.keyboard.value, "Unsent draft")
        self.tick("BACK")
        for _ in range(10):
            self.tick("UP")
        self.tick("DOWN")
        self.assertGreaterEqual(self.app.scroll, 0)

    def test_configured_identity_opens_home_without_keyboard(self):
        self.assertEqual(self.app.chat.username, "alice")
        self.assertEqual(self.app.view, "home")
        self.assertIsNone(self.app.keyboard)
        self.assertIn("badge settings", self.app.identity_source)

    def test_identity_uses_profile_login_not_display_name(self):
        self.secrets.GITHUB_USERNAME = ""
        with patch("builtins.open", mock_open(read_data='{"name":"Display Name","login":"@Bob"}')):
            self.app = self.namespace["AttendeeChat"]()
        self.assertEqual(self.app.chat.username, "bob")
        self.assertIn("badge profile", self.app.identity_source)
        self.assertEqual(self.app.view, "home")

    def test_missing_profile_uses_device_id_without_keyboard(self):
        self.secrets.GITHUB_USERNAME = ""
        with patch("builtins.open", side_effect=FileNotFoundError(2, "not found")):
            self.app = self.namespace["AttendeeChat"]()
        self.assertEqual(self.app.chat.username, "badge-" + "17" * 8)
        self.assertEqual(self.app.view, "home")
        self.assertIn("no GitHub handle", self.app.identity_source)

    def test_invalid_profiles_report_problem_and_use_device_id(self):
        self.secrets.GITHUB_USERNAME = "invalid user"
        for data in ("bad json", "[]", '{"login":42}', '{"name":"Not a login"}'):
            with self.subTest(data=data), patch("builtins.open", mock_open(read_data=data)):
                with patch("builtins.print") as output:
                    app = self.namespace["AttendeeChat"]()
                self.assertEqual(app.chat.username, "badge-" + "17" * 8)
                self.assertEqual(app.view, "home")
                output.assert_called()

    def test_profile_io_failure_is_logged(self):
        self.secrets.GITHUB_USERNAME = ""
        with patch("builtins.open", side_effect=OSError(5, "I/O error")):
            with patch("builtins.print") as output:
                self.app = self.namespace["AttendeeChat"]()
        self.assertEqual(self.app.view, "home")
        self.assertTrue(any("cannot read badge profile" in str(call) for call in output.call_args_list))

    def test_sender_demo_waits_for_acceptance_then_notifies(self):
        self.app.selection = 2
        self.tick("SELECT")
        self.tick(frames=40)
        self.assertEqual(self.app.chat.state, "outgoing")
        self.assertEqual(self.app.view, "connect")
        self.assertFalse(self.app.chat.send("t", "not accepted"))
        self.tick(frames=160)
        self.assertEqual(self.app.view, "chat")
        self.assertGreater(self.app.accepted_ms, 0)
        labels = [call.args[0] for call in self.screen.text.call_args_list]
        self.assertIn("Chat accepted! You can message now.", labels)
        self.badgelink.Link.assert_not_called()
        self.tick(frames=210)
        self.assertEqual(self.app.accepted_ms, 0)

    def test_request_and_receive_buttons_never_open_identity_keyboard(self):
        for selection, expected in ((0, "searching"), (1, "listening")):
            self.app = self.namespace["AttendeeChat"]()
            self.app.selection = selection
            self.tick("SELECT")
            self.assertEqual(self.app.view, "connect")
            self.assertEqual(self.app.chat.state, expected)
            self.assertIsNone(self.app.keyboard)

    def test_keyboard_case_space_delete_limit_and_navigation(self):
        keyboard = self.namespace["Keyboard"]("")
        for key, expected in (("a", "a"), ("Aa", "a"), ("B", "aB"),
                              ("Space", "aB "), ("Del", "aB")):
            keyboard.cursor = keyboard.keys().index(key)
            self.pressed.add("SELECT")
            keyboard.update()
            self.pressed.clear()
            self.assertEqual(keyboard.value, expected)
        keyboard.value = "x" * 96
        keyboard.cursor = 0
        self.pressed.add("SELECT")
        keyboard.update()
        self.assertEqual(len(keyboard.value), 96)
        self.assertIn("96", keyboard.error)
        for key in ("LEFT", "RIGHT", "UP", "DOWN"):
            self.pressed = {key}
            keyboard.update()
            self.assertTrue(0 <= keyboard.cursor < len(keyboard.keys()))

    def test_no_radio_firmware_still_supports_demo(self):
        self.namespace["badgelink"] = None
        self.app = self.namespace["AttendeeChat"]()
        self.app.start(True)
        self.assertIn("unavailable", self.app.notice)
        self.demo()
        self.badgelink.Link.assert_not_called()

    def test_browser_demo_does_not_require_os_urandom(self):
        del self.modules["os"].urandom
        self.demo()
        self.badgelink.Link.assert_not_called()

    def test_simulator_defaults_to_usb_test_without_radio_or_urandom(self):
        self.modules["sys"].platform = "webassembly"
        del self.modules["os"].urandom
        self.secrets.GITHUB_USERNAME = ""
        with patch("builtins.open", side_effect=FileNotFoundError(2, "not found")):
            self.load_app()
        self.assertEqual(self.app.chat.username, "badge-simulator")
        self.assertEqual(self.app.selection, 2)
        self.assertTrue(self.app.usb)
        self.app.selection = 0
        self.tick("SELECT")
        self.assertEqual(self.app.view, "connect")
        self.assertEqual(self.app.chat.state, "searching")
        relay = self.app.link
        self.assertIsInstance(relay, self.modules["usb_relay"].UsbRelay)
        self.assertFalse(relay.serial)
        self.tick()
        self.assertTrue(relay.want)
        self.assertEqual(relay.exchange([]), ["50"])
        self.badgelink.Link.assert_not_called()
        self.tick("BACK")
        self.assertEqual(self.app.view, "result")
        self.tick("BACK")
        self.assertEqual(self.app.view, "home")
        self.assertFalse(relay.want)
        self.app.selection = 4
        self.tick("SELECT")
        self.assertFalse(self.app.usb)
        self.app.selection = 1
        self.tick("SELECT")
        self.assertEqual(self.app.view, "home")
        self.assertIn("Simulator has no radio", self.app.notice)
        self.badgelink.Link.assert_not_called()
        self.demo()

    def test_simulator_and_badge_chat_through_usb_relay(self):
        self.modules["sys"].platform = "webassembly"
        self.load_app()
        sender = self.app
        self.app = self.namespace["AttendeeChat"]()
        receiver = self.app
        receiver.chat.username = "bob"
        sender.chat.username = "alice"
        sender.start(True)
        receiver.start(False)

        def frames(count, key_for=None, key=None):
            for _ in range(count):
                self.clock.ticks += self.clock.ticks_delta
                for app in (sender, receiver):
                    self.app = app
                    self.pressed.clear()
                    if app is key_for:
                        self.pressed.add(key)
                    app.update()
                    app.draw()
                key_for = None
                receiver.link.exchange(sender.link.exchange(receiver.link.exchange([])))
            self.pressed.clear()

        frames(60)
        self.assertEqual(receiver.view, "offer")
        self.assertEqual(receiver.chat.peer, "alice")
        frames(1, receiver, "SELECT")
        frames(60)
        self.assertEqual(sender.chat.state, "active")
        self.assertEqual(receiver.chat.state, "active")
        self.assertGreater(sender.accepted_ms, 0)
        self.assertTrue(sender.chat.send("t", "hi bob"))
        self.assertTrue(receiver.chat.send("e", 5))
        frames(60)
        self.assertIn(("t", "hi bob"), [(e["kind"], e["value"]) for e in receiver.chat.history
                                        if not e["mine"]])
        self.assertIn(("e", 5), [(e["kind"], e["value"]) for e in sender.chat.history
                                 if not e["mine"]])

    def test_usb_toggle_on_badge_uses_serial_relay(self):
        relay = Mock(spec=self.modules["usb_relay"].UsbRelay)
        relay.linked = False
        relay.partner = None
        with patch.dict(self.namespace, {"UsbRelay": Mock(return_value=relay)}):
            self.assertFalse(self.app.usb)
            self.app.selection = 4
            self.tick("SELECT")
            self.assertTrue(self.app.usb)
            self.app.selection = 1
            self.tick("SELECT")
            self.namespace["UsbRelay"].assert_called_once_with(True)
        self.assertEqual(self.app.chat.state, "listening")
        self.badgelink.Link.assert_not_called()

    def test_keyboard_command_labels_fit_their_cells(self):
        keyboard = self.namespace["Keyboard"]("")
        rows = keyboard.rows()
        self.assertEqual([key for row in rows for key in row], keyboard.keys())
        command_width = (self.screen.width - 16) // len(rows[-1])
        for key in rows[-1]:
            self.assertLess(self.screen.measure_text(key)[0], command_width - 4)

    def test_failed_radio_setup_closes_partially_created_link(self):
        radio = self.badgelink.Link.return_value
        self.badgelink.Proximity.side_effect = OSError("radio busy")
        self.app.start(True)
        radio.close.assert_called_once()
        self.assertIsNone(self.app.link)
        self.assertIn("radio busy", self.app.notice)
        self.demo()

    def test_exit_closes_radio(self):
        self.app.link = Mock()
        self.namespace["on_exit"]()
        self.app.link.close.assert_called_once()


class UsbRelayTests(unittest.TestCase):
    def test_links_only_while_both_sides_want_and_rejects_bad_input(self):
        relay_module = load("usb_relay")
        a, b = relay_module.UsbRelay(False), relay_module.UsbRelay(False)
        a.want = True
        a.pump(0)
        b.pump(0)
        b.exchange(a.exchange([]))
        self.assertFalse(b.linked)
        b.want = True
        b.pump(10)
        a.exchange(b.exchange(a.exchange([])))
        self.assertTrue(a.linked)
        b.exchange(["zz", "5", "", None, "00" * 200, "4869"])
        self.assertTrue(b.send(b"Hi"))
        a.exchange(b.exchange([]))
        self.assertEqual(a.receive(), [b"Hi"])
        self.assertEqual(b.receive(), [b"Hi"])
        a.pump(10 + relay_module.TIMEOUT_MS)
        self.assertFalse(a.linked)
        self.assertFalse(a.send(b"late"))


if __name__ == "__main__":
    unittest.main()
