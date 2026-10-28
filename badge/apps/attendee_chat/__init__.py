"""Nearby attendee chat for the Universe 2026 badge."""

import binascii
import json
import os
import random
import sys

APP_DIR = "/system/apps/attendee_chat"
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

from chat_protocol import Chat, EMOJIS, MAX_TEXT, handle
from chat_demo import Demo
from usb_relay import NullProximity, UsbRelay

try:
    from badgeware import link as badgelink
except ImportError:
    badgelink = None

badge.mode(HIRES | VSYNC)
screen.antialias = image.OFF
screen.font = font.nope
screen.fill_rule = image.EVEN_ODD

BG = color.rgb(13, 17, 28)
PANEL = color.rgb(28, 35, 54)
WHITE = color.rgb(239, 244, 255)
MUTED = color.rgb(162, 175, 199)
ACCENT = color.rgb(129, 247, 179)
WARNING = color.rgb(255, 186, 113)
INK = color.rgb(13, 17, 28)
emoji_sheet = image.load("emoji.png").spritesheet(6, 1)
SIMULATOR = sys.platform == "webassembly"


def new_nonce():
    urandom = getattr(os, "urandom", None)
    if urandom is not None:
        return binascii.hexlify(urandom(8)).decode()
    return "%08x%08x" % (random.getrandbits(32), random.getrandbits(32))


def identity():
    try:
        import secrets
    except ImportError:
        secrets = None
    configured = getattr(secrets, "GITHUB_USERNAME", "")
    username = handle(configured)
    if username:
        return username, "GitHub handle from badge settings"
    if configured:
        print("attendee_chat: invalid GITHUB_USERNAME; checking badge profile")
    try:
        with open("/state/badge_user.json") as source:
            profile = json.load(source)
        username = handle(profile.get("login")) if isinstance(profile, dict) else ""
        if username:
            return username, "GitHub handle from badge profile"
        print("attendee_chat: badge profile has no valid GitHub login; using badge ID")
    except OSError as error:
        if error.errno != 2:
            print("attendee_chat: cannot read badge profile:", error)
    except ValueError as error:
        print("attendee_chat: invalid badge profile:", error)
    if SIMULATOR:
        return "badge-simulator", "Simulated badge ID / no radio"
    from machine import unique_id
    return "badge-" + binascii.hexlify(unique_id()).decode(), "Badge ID / no GitHub handle configured"


def text(value, x, y, pen=WHITE):
    screen.pen = pen
    screen.text(value, x, y)


def fit(value, width):
    if screen.measure_text(value)[0] <= width:
        return value
    while value and screen.measure_text(value + "...")[0] > width:
        value = value[:-1]
    return value + "..."


def lines(value, width):
    result = []
    line = ""
    for character in value:
        if line and screen.measure_text(line + character)[0] > width:
            split = line.rfind(" ")
            if split > 0:
                result.append(line[:split])
                line = line[split + 1:]
            else:
                result.append(line)
                line = ""
        line += character
    return result + [line]


class Keyboard:
    def __init__(self, value):
        self.value = value
        self.cursor = 0
        self.upper = False
        self.error = ""

    def keys(self):
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if self.upper else "abcdefghijklmnopqrstuvwxyz"
        keys = list(alphabet + "0123456789-")
        keys += list(".,!?'():/")
        return keys + ["Space", "Aa", "Del", "Emoji", "Close", "Send"]

    def rows(self):
        keys = self.keys()
        commands = 6
        letters = keys[:-commands]
        return [letters[index:index + 10] for index in range(0, len(letters), 10)] + [keys[-commands:]]

    def update(self):
        keys = self.keys()
        if badge.pressed(BUTTON_LEFT):
            self.cursor = (self.cursor - 1) % len(keys)
        elif badge.pressed(BUTTON_RIGHT):
            self.cursor = (self.cursor + 1) % len(keys)
        elif badge.pressed(BUTTON_UP) or badge.pressed(BUTTON_DOWN):
            rows = self.rows()
            column = self.cursor
            row = 0
            while column >= len(rows[row]):
                column -= len(rows[row])
                row += 1
            direction = -1 if badge.pressed(BUTTON_UP) else 1
            row = (row + direction) % len(rows)
            self.cursor = sum(len(items) for items in rows[:row]) + min(column, len(rows[row]) - 1)
        if badge.pressed(BUTTON_BACK):
            return "cancel"
        if not badge.pressed(BUTTON_SELECT):
            return None
        key = keys[self.cursor]
        self.error = ""
        if key == "Send":
            return "done"
        if key == "Close":
            return "cancel"
        if key == "Emoji":
            return "emoji"
        if key == "Del":
            self.value = self.value[:-1]
        elif key == "Aa":
            self.upper = not self.upper
        elif len(self.value) < MAX_TEXT:
            self.value += " " if key == "Space" else key
        else:
            self.error = "Message limit: 96"
        return None

    def draw(self):
        screen.pen = PANEL
        screen.rectangle(8, 39, screen.width - 16, 45)
        shown = lines(self.value + "_", screen.width - 28)[-3:]
        for index, line in enumerate(shown):
            text(line, 14, 43 + index * 12)
        rows = self.rows()
        index = 0
        for row, items in enumerate(rows):
            cell = (screen.width - 16) // (len(items) if row == len(rows) - 1 else 10)
            for column, key in enumerate(items):
                x = 8 + column * cell
                y = 93 + row * 18
                selected = index == self.cursor
                screen.pen = ACCENT if selected else PANEL
                screen.rectangle(x, y, cell - 2, 16)
                text(key, x + 2, y + 3, INK if selected else WHITE)
                index += 1
        text(self.error or "Arrows: move  Select: key",
             8, screen.height - 18, WARNING if self.error else MUTED)


class AttendeeChat:
    def __init__(self):
        self.notice = ""
        username, self.identity_source = identity()
        self.chat = Chat(username)
        self.link = None
        self.proximity = None
        self.demo = None
        self.radio_error = ""
        if SIMULATOR:
            self.radio_error = "Simulator has no radio. Choose a demo below."
        elif badgelink is None:
            self.radio_error = "Firmware badge link is unavailable"
        if self.radio_error:
            print("attendee_chat:", self.radio_error)
        self.usb = SIMULATOR
        self.was_linked = False
        self.view = "home"
        self.selection = 2 if SIMULATOR else 0
        self.scroll = 0
        self.keyboard = None
        self.draft = ""
        self.emoji = 0
        self.accepted_ms = 0

    def edit(self):
        self.keyboard = Keyboard(self.draft)
        self.view = "keyboard"

    def start(self, requesting):
        if self.link is not None and isinstance(self.link, UsbRelay) != self.usb:
            self.link.close()
            self.link = self.proximity = None
        if self.usb:
            if self.link is None:
                self.link = UsbRelay(not SIMULATOR)
                self.proximity = NullProximity()
        elif self.radio_error:
            self.notice = self.radio_error
            self.view = "home"
            return
        elif self.link is None:
            radio = None
            try:
                radio = badgelink.Link("attendee_chat")
                proximity = badgelink.Proximity(radio)
            except OSError as error:
                if radio is not None:
                    radio.close()
                print("attendee_chat: cannot start radio:", error)
                self.notice = "Cannot start radio: " + str(error)
                self.view = "home"
                return
            self.link = radio
            self.proximity = proximity
        if self.chat.start("", new_nonce(), request=requesting):
            self.view = "connect"
            self.notice = ""
            self.scroll = 0
        else:
            self.notice = self.chat.status
            self.view = "home"

    def start_demo(self, requesting=False):
        self.release()
        if self.link is not None:
            self.link.close()
            self.link = self.proximity = None
        self.demo = Demo(self.chat, requesting)
        self.view = "connect"
        self.scroll = 0
        self.draft = ""
        self.accepted_ms = 0

    def release(self):
        if self.link is not None:
            partner = self.link.partner
            self.proximity.rest(partner.id if partner else None, badge.ticks)
            self.link.leave()
        self.was_linked = False
        self.chat.linked = False

    def sync_view(self):
        state = self.chat.state
        if state == "ended":
            self.view = "result"
        elif state in ("incoming", "accepting"):
            self.view = "offer"
        elif state == "active":
            if self.view not in ("keyboard", "emoji", "leave"):
                self.view = "chat"
        elif state in ("searching", "listening", "connecting", "outgoing"):
            self.view = "connect"

    def keyboard_frame(self):
        action = self.keyboard.update()
        if action in ("cancel", "emoji"):
            self.draft = self.keyboard.value
            self.keyboard = None
            self.view = "emoji" if action == "emoji" else "chat"
        elif action == "done":
            if self.chat.send("t", self.keyboard.value):
                self.draft = ""
                self.keyboard = None
                self.scroll = 0
                self.view = "chat"
            else:
                self.keyboard.error = self.chat.status

    def input_frame(self):
        if self.view == "keyboard":
            self.keyboard_frame()
        elif self.view == "home":
            if badge.pressed(BUTTON_UP):
                self.selection = (self.selection - 1) % 5
            elif badge.pressed(BUTTON_DOWN):
                self.selection = (self.selection + 1) % 5
            if badge.pressed(BUTTON_SELECT):
                if self.selection == 0:
                    self.start(True)
                elif self.selection == 1:
                    self.start(False)
                elif self.selection == 2:
                    self.start_demo(True)
                elif self.selection == 3:
                    self.start_demo(False)
                else:
                    self.usb = not self.usb
                    self.notice = ""
        elif self.view == "connect":
            if badge.pressed(BUTTON_BACK):
                self.chat.close()
        elif self.view == "offer":
            if badge.pressed(BUTTON_BACK):
                if self.chat.state == "incoming":
                    self.chat.decline()
                else:
                    self.chat.close()
            elif badge.pressed(BUTTON_SELECT) and self.chat.state == "incoming":
                self.chat.accept()
        elif self.view == "chat":
            if badge.pressed(BUTTON_SELECT):
                self.edit()
            elif badge.pressed(BUTTON_MENU):
                self.view = "emoji"
            elif badge.pressed(BUTTON_BACK):
                self.view = "leave"
            elif badge.pressed(BUTTON_UP):
                self.scroll = min(self.scroll + 1, max(0, len(self.transcript()) - 7))
            elif badge.pressed(BUTTON_DOWN):
                self.scroll = max(0, self.scroll - 1)
        elif self.view == "emoji":
            if badge.pressed(BUTTON_RIGHT):
                self.emoji = (self.emoji + 1) % 6
            elif badge.pressed(BUTTON_LEFT):
                self.emoji = (self.emoji - 1) % 6
            elif badge.pressed(BUTTON_UP) or badge.pressed(BUTTON_DOWN):
                self.emoji = (self.emoji + 3) % 6
            if badge.pressed(BUTTON_BACK):
                self.view = "chat"
            elif badge.pressed(BUTTON_SELECT) and self.chat.send("e", self.emoji):
                self.scroll = 0
                self.view = "chat"
        elif self.view == "leave":
            if badge.pressed(BUTTON_SELECT):
                self.chat.close()
            elif badge.pressed(BUTTON_BACK):
                self.view = "chat"
        elif self.view == "result":
            if badge.pressed(BUTTON_SELECT) or badge.pressed(BUTTON_BACK):
                self.release()
                self.demo = None
                self.chat = Chat(self.chat.username)
                self.draft = ""
                self.keyboard = None
                self.accepted_ms = 0
                self.view = "home"

    def update(self):
        try:
            previous_state = self.chat.state
            self.accepted_ms = max(0, self.accepted_ms - badge.ticks_delta)
            if self.demo is not None:
                self.demo.pump(badge.ticks_delta)
            if self.link is not None:
                if isinstance(self.link, UsbRelay):
                    self.link.want = (self.chat.state in ("searching", "listening")
                                      or self.chat.linked)
                    self.link.pump(badge.ticks)
                else:
                    self.link.pump()
                linked = self.link.linked
                if linked and not self.was_linked:
                    if self.chat.state in ("searching", "listening"):
                        self.chat.connected()
                    else:
                        self.link.leave()
                        linked = False
                elif self.was_linked and not linked:
                    self.chat.disconnected()
                    self.proximity.clear()
                self.was_linked = linked
                if linked:
                    for packet in self.link.receive():
                        message = self.chat.wire.receive(packet)
                        if message is not None:
                            self.chat.receive(message)
            self.chat.step(badge.ticks_delta)
            self.sync_view()
            self.input_frame()
            self.sync_view()
            if previous_state != "active" and self.chat.state == "active":
                self.accepted_ms = 4000
            if self.link is not None:
                if self.chat.state in ("searching", "listening"):
                    self.proximity.update(badge.ticks)
                if self.chat.linked:
                    self.chat.wire.flush(self.link)
                self.link.update()
                if self.chat.state == "ended" and self.chat.age >= 500 and self.chat.linked:
                    self.release()
        except (OSError, ValueError) as error:
            print("attendee_chat: radio error:", error)
            self.chat.end("Radio error: " + str(error))
            self.release()
            self.view = "result"

    def transcript(self):
        rows = []
        for entry in self.chat.history:
            label = "Me" if entry["mine"] else ("Demo" if self.demo else "Peer")
            if entry["mine"]:
                label += " [" + entry["status"] + "]"
            rows.append((label, MUTED, None))
            if entry["kind"] == "e":
                rows.append((EMOJIS[entry["value"]], WHITE, entry["value"]))
                rows.append(("", WHITE, None))
            else:
                rows.extend((line, ACCENT if entry["mine"] else WHITE, None)
                            for line in lines(entry["value"], screen.width - 24))
        return rows

    def draw(self):
        screen.pen = BG
        screen.clear()
        screen.font = font.nope
        title = "ATTENDEE CHAT"
        if self.view == "keyboard":
            title = "WRITE A MESSAGE"
        text(title, 8, 10, ACCENT)
        tag = "NEARBY / UNVERIFIED"
        if self.demo:
            tag = "DEMO / NO RADIO"
        elif self.usb:
            tag = "USB TEST / NO RADIO"
        text(tag, screen.width - 132, 25, WARNING)
        if self.view == "keyboard":
            self.keyboard.draw()
            return
        if self.view == "home":
            text(fit("You: " + self.chat.username, screen.width - 16), 8, 49)
            labels = ("Request chat", "Ready to receive", "Demo: send request",
                      "Demo: receive request",
                      "Connection: " + ("USB test" if self.usb else "Nearby radio"))
            for index, label in enumerate(labels):
                screen.pen = ACCENT if index == self.selection else PANEL
                screen.rectangle(8, 66 + index * 25, screen.width - 16, 21)
                text(label, 15, 71 + index * 25, INK if index == self.selection else WHITE)
            hint = self.identity_source
            if self.usb:
                hint = "USB test: run tools/chat_usb_relay.py on the computer"
            elif self.radio_error:
                hint = self.radio_error
            self.paragraph(self.notice or hint, 194)
            self.footer("Up/Down: choose   Select: open")
        elif self.view == "connect":
            title = "Waiting for a receiver..." if self.chat.requesting else "Ready to receive"
            text(fit("To: " + self.chat.peer, screen.width - 16) if self.chat.peer else title, 8, 52)
            self.paragraph(self.chat.status, 83)
            self.paragraph(
                "Offline demo: the simulated receiver will accept your request." if self.demo else
                "USB test: the other side must choose USB test too, with the relay running." if self.usb else
                "One badge: Request chat. Other: Ready to receive. Hold back-to-back.", 124)
            self.paragraph("No messages until they accept. No venue-wide discovery.", 175)
            self.footer("Back: cancel   Home: exit")
        elif self.view == "offer":
            text(fit("From: " + self.chat.peer, screen.width - 16), 8, 55)
            self.paragraph("Accept this chat invitation?", 87, WHITE)
            self.paragraph(
                "Simulated attendee. No real person or radio is connected." if self.demo else
                "This ID is self-reported, not verified by GitHub. Confirm in person.",
                118, WARNING)
            self.paragraph(self.chat.status, 170)
            self.footer("Select: accept   Back: decline / cancel")
        elif self.view == "chat":
            text(fit("Chat: " + self.chat.peer, screen.width - 16), 8, 43)
            if self.accepted_ms:
                screen.pen = ACCENT
                screen.rectangle(8, 59, screen.width - 16, 18)
                text("Chat accepted! You can message now.", 12, 64, INK)
            rows = self.transcript()
            end = max(0, len(rows) - self.scroll)
            start = max(0, end - 7)
            if not rows:
                text("Invitation accepted. Say hello!", 8, 86, MUTED)
            for index, (line, pen, emoji) in enumerate(rows[start:end]):
                y = 82 + index * 14
                if emoji is None:
                    text(line, 12, y, pen)
                else:
                    screen.blit(emoji_sheet.sprite(emoji, 0), vec2(12, y))
                    text(line, 44, y + 5)
            text(fit(self.chat.status, screen.width - 16), 8, screen.height - 42, WARNING)
            self.footer("Select: keyboard (has Emoji)  Menu: emoji")
        elif self.view == "emoji":
            for index, label in enumerate(EMOJIS):
                x = 8 + (index % 3) * ((screen.width - 16) // 3)
                y = 59 + (index // 3) * 65
                screen.pen = ACCENT if index == self.emoji else PANEL
                screen.rectangle(x, y, (screen.width - 22) // 3, 57)
                screen.blit(emoji_sheet.sprite(index, 0), vec2(x + 36, y + 6))
                text(label, x + 5, y + 40, INK if index == self.emoji else WHITE)
            text(fit(self.chat.status, screen.width - 16), 8, 199, WARNING)
            self.footer("Arrows: choose  Select: send  Back: cancel")
        elif self.view == "leave":
            self.paragraph("End this chat?", 77, WHITE)
            self.paragraph("Reconnecting will require a new invitation and acceptance.", 112)
            self.footer("Select: end chat   Back: keep chatting")
        else:
            self.paragraph(self.chat.status, 70, WARNING)
            self.paragraph("Consent is not saved. Start a new invitation to chat again.", 126)
            self.footer("Select / Back: return to home")

    def paragraph(self, value, y, pen=MUTED):
        for index, line in enumerate(lines(value, screen.width - 20)[:3]):
            text(line, 8, y + index * 13, pen)

    def footer(self, value):
        text(value, 8, screen.height - 18, MUTED)


app = AttendeeChat()


def update():
    app.update()
    app.draw()


def on_exit():
    if app.link is not None:
        app.link.close()
    app.chat = Chat(app.chat.username)
    app.demo = app.keyboard = None
    app.draft = ""


run(update)
