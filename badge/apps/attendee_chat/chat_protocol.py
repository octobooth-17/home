"""Bounded, consent-gated messages over the firmware's ordered badge link."""

import json


MAX_TEXT = 96
EMOJIS = ("Smile", "Heart", "Thumbs up", "Wave", "Star", "Rocket")
HISTORY_LIMIT = 24
INVITE_MS = 30000
RETRY_MS = 1500
DELIVERY_MS = 12000


def handle(value):
    if not isinstance(value, str):
        return ""
    value = value.strip().lstrip("@").lower()
    if not 1 <= len(value) <= 39 or value[0] == "-" or value[-1] == "-" or "--" in value:
        return ""
    if any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in value):
        return ""
    return value


def valid_text(value):
    return (isinstance(value, str) and 0 < len(value) <= MAX_TEXT
            and bool(value.strip()) and all(32 <= ord(c) <= 126 for c in value))


def valid_id(value):
    return (isinstance(value, str) and len(value) == 16
            and all(c in "0123456789abcdef" for c in value))


class Wire:
    MAX_BYTES = 384
    MAX_PARTS = 192

    def __init__(self):
        self.outbox = []
        self.frames = None
        self.sent = 0
        self.parts = []
        self.total = 0

    def queue(self, message):
        raw = json.dumps(message).encode()
        if len(raw) > self.MAX_BYTES:
            raise ValueError("Message is too large")
        if raw not in self.outbox:
            if len(self.outbox) >= 8:
                raise ValueError("Radio queue is full")
            self.outbox.append(raw)

    def flush(self, link):
        if not self.outbox:
            return
        if self.frames is None:
            size = link.capacity() - 3
            if size < 2:
                raise ValueError("Radio packet capacity is too small")
            raw = self.outbox[0]
            count = (len(raw) + size - 1) // size
            if count > self.MAX_PARTS:
                raise ValueError("Too many radio fragments")
            self.frames = [
                b"C" + bytes((i, count)) + raw[i * size:(i + 1) * size]
                for i in range(count)
            ]
            self.sent = 0
        for _ in range(4):
            if not link.send(self.frames[self.sent]):
                return
            self.sent += 1
            if self.sent == len(self.frames):
                self.outbox.pop(0)
                self.frames = None
                return

    def receive(self, packet):
        if not isinstance(packet, (bytes, bytearray)) or len(packet) < 4 or packet[:1] != b"C":
            raise ValueError("Invalid radio packet")
        index, total = packet[1], packet[2]
        if not 1 <= total <= self.MAX_PARTS or index >= total:
            raise ValueError("Invalid radio fragment count")
        if index == 0:
            self.parts = []
            self.total = total
        if total != self.total or index != len(self.parts):
            raise ValueError("Radio fragments arrived out of order")
        self.parts.append(packet[3:])
        if sum(len(part) for part in self.parts) > self.MAX_BYTES:
            raise ValueError("Incoming message is too large")
        if len(self.parts) != total:
            return None
        raw = b"".join(self.parts)
        self.parts = []
        self.total = 0
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ValueError("Invalid message encoding")
        if not isinstance(value, list) or not value or not isinstance(value[0], str):
            raise ValueError("Invalid message format")
        return value


class Chat:
    def __init__(self, username):
        self.username = handle(username)
        self.state = "idle"
        self.status = ""
        self.linked = False
        self.target = ""
        self.requesting = False
        self.peer = ""
        self.session = ""
        self.nonce = ""
        self.role = ""
        self.age = 0
        self.retry = 0
        self.sequence = 0
        self.received = 0
        self.pending = None
        self.history = []
        self.wire = Wire()

    def start(self, target, nonce, request=False):
        requested = target
        target = handle(target) if target else ""
        if (not self.username or not isinstance(requested, str) or (requested and not target)
                or (target and target == self.username) or not valid_id(nonce)):
            self.status = "Use a different, valid GitHub handle"
            return False
        self.target = target
        self.requesting = bool(target) or request
        self.nonce = nonce
        self.peer = ""
        self.session = ""
        self.role = ""
        self.linked = False
        self.age = self.retry = self.sequence = self.received = 0
        self.pending = None
        self.history = []
        self.wire = Wire()
        self.state = "searching" if self.requesting else "listening"
        self.status = "Looking for a receiver" if self.requesting else "Ready to receive a request"
        return True

    def connected(self):
        self.linked = True
        self.state = "connecting"
        self.age = self.retry = 0
        self.wire.queue(["H", self.username])
        self.status = "Detecting nearby badge..."

    def disconnected(self):
        self.linked = False
        self.end("Badge disconnected; invite again")
        self.wire = Wire()

    def end(self, reason):
        if self.pending is not None:
            self.pending["status"] = "unconfirmed"
            self.pending = None
        self.state = "ended"
        self.status = reason
        self.age = 0

    def close(self):
        if self.linked:
            self.wire.queue(["E", self.session])
        self.end("Chat closed; acceptance cleared")

    def accept(self):
        if self.state != "incoming":
            return
        self.state = "accepting"
        self.age = self.retry = 0
        self.wire.queue(["A", self.session])
        self.status = "Confirming acceptance..."

    def decline(self):
        if self.state == "incoming":
            self.wire.queue(["D", self.session])
        self.end("Invitation declined")

    def _active(self):
        self.state = "active"
        self.age = self.retry = 0
        self.status = "Chat accepted! Connected"

    def _append(self, entry):
        self.history.append(entry)
        if len(self.history) > HISTORY_LIMIT:
            self.history.pop(0)

    def send(self, kind, value):
        if self.state != "active":
            self.status = "Invitation must be accepted first"
            return False
        if self.pending is not None:
            self.status = "Wait for delivery confirmation"
            return False
        if not self._content(kind, value):
            self.status = "Use 1-96 printable characters"
            return False
        self.sequence += 1
        entry = {"mine": True, "kind": kind, "value": value,
                 "status": "sending", "number": self.sequence, "age": 0}
        self.wire.queue(["M", self.session, self.sequence, kind, value])
        self.pending = entry
        self._append(entry)
        self.retry = 0
        self.status = "Sending..."
        return True

    @staticmethod
    def _content(kind, value):
        return ((kind == "t" and valid_text(value))
                or (kind == "e" and type(value) is int and 0 <= value < len(EMOJIS)))

    def receive(self, message):
        if self.state in ("idle", "ended") or not self.linked:
            return
        kind = message[0]
        if kind == "H" and len(message) == 2:
            peer = handle(message[1])
            if not peer or peer == self.username or (self.peer and peer != self.peer):
                self.end("Invalid or changed peer handle")
                return
            self.peer = peer
            if self.state == "connecting":
                if self.target and peer != self.target:
                    self.end("Nearby handle does not match target")
                elif self.requesting:
                    self.target = peer
                    self.session = self.nonce
                    self.role = "sender"
                    self.state = "outgoing"
                    self.age = self.retry = 0
                    self.wire.queue(["I", self.username, self.target, self.session])
                    self.status = "Waiting for their acceptance"
                else:
                    self.status = "Waiting for an invitation"
            return
        if kind == "I" and len(message) == 4:
            sender, target, session = message[1:]
            if sender != self.peer or target != self.username or not valid_id(session):
                return
            if self.state in ("accepting", "active"):
                if session == self.session and self.role == "receiver":
                    self.wire.queue(["A", self.session])
                return
            if self.state == "incoming":
                return
            # Simultaneous invitations converge on the alphabetically first sender.
            if self.state == "outgoing" and self.username < self.peer:
                return
            if self.state not in ("connecting", "outgoing"):
                return
            self.session = session
            self.role = "receiver"
            self.state = "incoming"
            self.age = self.retry = 0
            self.status = "Accept chat from " + sender + "?"
            return
        if len(message) < 2 or not self.session or message[1] != self.session:
            return
        if kind == "A" and len(message) == 2 and self.role == "sender":
            if self.state in ("outgoing", "active"):
                self.wire.queue(["C", self.session])
                self._active()
        elif kind == "C" and len(message) == 2 and self.role == "receiver":
            if self.state == "accepting":
                self._active()
        elif kind in ("D", "E") and len(message) == 2:
            self.end("They declined or closed the chat")
        elif kind == "M" and len(message) == 5 and self.state == "active":
            number, content_kind, value = message[2:]
            if type(number) is not int or not 1 <= number <= 0x3FFFFFFF:
                return
            if not self._content(content_kind, value):
                return
            if number > self.received:
                self.received = number
                self._append({"mine": False, "kind": content_kind,
                              "value": value, "status": "received"})
            self.wire.queue(["K", self.session, number])
        elif kind == "K" and len(message) == 3 and self.state == "active":
            if self.pending is not None and type(message[2]) is int:
                if message[2] == self.pending["number"]:
                    self.pending["status"] = "delivered"
                    self.pending = None
                    self.status = "Delivered"

    def step(self, elapsed):
        elapsed = max(0, elapsed)
        self.age += elapsed
        self.retry += elapsed
        if self.state in ("connecting", "outgoing", "incoming", "accepting"):
            if self.age >= INVITE_MS:
                self.close()
                self.status = "Invitation timed out; try again"
                return
        if not self.linked:
            return
        if self.pending is not None:
            self.pending["age"] += elapsed
            if self.pending["age"] >= DELIVERY_MS:
                self.pending["status"] = "unconfirmed"
                self.pending = None
                self.status = "Delivery unconfirmed; may have arrived"
        if self.retry < RETRY_MS:
            return
        self.retry = 0
        if self.state == "connecting":
            self.wire.queue(["H", self.username])
        elif self.state == "outgoing":
            self.wire.queue(["H", self.username])
            self.wire.queue(["I", self.username, self.target, self.session])
        elif self.state == "accepting":
            self.wire.queue(["A", self.session])
        if self.pending is not None:
            entry = self.pending
            self.wire.queue(["M", self.session, entry["number"], entry["kind"], entry["value"]])
