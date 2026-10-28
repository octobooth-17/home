"""Transient native demo check; mount badge/apps/attendee_chat at /remote."""

import os
import sys


native_badge = badge
native_image = image
sys.path.insert(0, "/remote")


class ProbeBadge:
    def __init__(self):
        self.keys = set()
        self.ticks = 0
        self.ticks_delta = 20

    def pressed(self, key):
        return key in self.keys

    def mode(self, flags):
        native_badge.mode(flags)


class ProbeImages:
    OFF = native_image.OFF
    EVEN_ODD = native_image.EVEN_ODD

    def load(self, path):
        with open(path, "rb") as source:
            return native_image.load(source.read())


namespace = dict(globals())
controls = ProbeBadge()
namespace["badge"] = controls
namespace["image"] = ProbeImages()
with open("/remote/__init__.py") as source:
    code = source.read().split("\napp = AttendeeChat()")[0]
code = code.replace('APP_DIR = "/system/apps/attendee_chat"', 'APP_DIR = "/remote"')
exec(code, namespace)
namespace["identity"] = lambda: ("probe-user", "Transient test ID")
app = namespace["AttendeeChat"]()


def frame(key=None, count=1):
    for _ in range(count):
        controls.keys = {key} if key is not None else set()
        controls.ticks += controls.ticks_delta
        app.update()
        app.draw()
        display.update()
        assert any(screen.raw), "Empty native framebuffer"
    controls.keys = set()


try:
    assert app.link is None, "Radio opened before explicit invitation"
    frame()
    app.selection = 3
    frame(BUTTON_SELECT)
    frame(count=80)
    assert app.view == "offer", app.view
    frame(BUTTON_SELECT)
    frame(count=100)
    assert app.view == "chat", app.view

    frame(BUTTON_SELECT)
    assert app.view == "keyboard"
    app.keyboard.value = "Hello from one badge!"
    app.keyboard.cursor = app.keyboard.keys().index("Send")
    frame(BUTTON_SELECT)
    frame(count=100)
    assert app.chat.history[-1]["value"] == "Demo echo: Hello from one badge!"

    for index in range(6):
        frame(BUTTON_MENU)
        assert app.view == "emoji"
        app.emoji = index
        frame(BUTTON_SELECT)
        frame(count=60)
        assert app.chat.history[-1]["kind"] == "e"
        assert app.chat.history[-1]["value"] == index

    frame(BUTTON_BACK)
    assert app.view == "leave"
    frame(BUTTON_BACK)
    assert app.view == "chat"
    frame(BUTTON_BACK)
    frame(BUTTON_SELECT)
    assert app.view == "result"
    frame(BUTTON_SELECT)
    assert app.view == "home"
    assert app.demo is None and not app.chat.history
    assert app.link is None, "Offline demo opened a real radio"

    app.edit()
    frame()
    app.keyboard.value = "x" * 39
    frame()
    for label in ("DEMO / NO RADIO", "Select: text  Menu: emoji  Back: end",
                  "Arrows: choose  Select: send  Back: cancel"):
        assert screen.measure_text(label)[0] <= screen.width - 16, label
    app.view = "home"
    app.start(True)
    assert app.link is not None, app.notice
    frame(count=3)
    assert app.chat.state == "searching", app.chat.status
    print("ATTENDEE_CHAT_RADIO_INIT_PASS: native Link and Proximity initialized")
    print("ATTENDEE_CHAT_NATIVE_PASS: invitation, text echo, six emoji, cleanup, native rendering")
    print("Native screen:", screen.width, screen.height)
finally:
    if app.link is not None:
        app.link.close()
