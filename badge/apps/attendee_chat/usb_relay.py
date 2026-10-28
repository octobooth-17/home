"""Test-only chat link relayed by tools/chat_usb_relay.py over the USB cable.

It mimics the parts of badgeware.link.Link the app uses. Packets travel as hex
lines: "~R<hex>" from this badge to the computer and "~T<hex>" back. Both sides
send a heartbeat only while they are ready to connect, so they link only when
both have chosen Request chat or Ready to receive.
"""

import binascii
import sys

HEARTBEAT = b"P"
HEARTBEAT_MS = 400
TIMEOUT_MS = 2500
CAPACITY = 120
QUEUE_LIMIT = 32
LINE_LIMIT = 2 * (CAPACITY + 8)


class NullProximity:
    def update(self, now):
        pass

    def clear(self):
        pass

    def rest(self, partner, now):
        pass


class UsbRelay:
    partner = None

    def __init__(self, serial):
        # serial=True on a badge (stdio); False in the simulator, where the
        # relay calls exchange() through the simulator's exec endpoint.
        self.serial = serial
        self.want = False
        self.now = 0
        self.seen = None
        self.beat = None
        self.inbox = []
        self.outbox = []
        self.line = ""
        self.poll = None
        if serial:
            import select
            self.poll = select.poll()
            self.poll.register(sys.stdin, select.POLLIN)

    @property
    def linked(self):
        return self.want and self.seen is not None and self.now - self.seen < TIMEOUT_MS

    def capacity(self):
        return CAPACITY

    def send(self, packet):
        if not self.linked or len(self.outbox) >= QUEUE_LIMIT:
            return False
        self.outbox.append(binascii.hexlify(packet).decode())
        return True

    def receive(self):
        packets, self.inbox = self.inbox, []
        return packets

    def accept(self, value):
        if not isinstance(value, str) or not value or len(value) > LINE_LIMIT:
            return
        try:
            packet = binascii.unhexlify(value)
        except ValueError:
            return
        if packet == HEARTBEAT:
            self.seen = self.now
        elif packet and self.linked and len(self.inbox) < QUEUE_LIMIT:
            self.seen = self.now
            self.inbox.append(packet)

    def exchange(self, incoming):
        if isinstance(incoming, list):
            for value in incoming[:QUEUE_LIMIT]:
                self.accept(value)
        outgoing, self.outbox = self.outbox, []
        return outgoing

    def pump(self, now):
        self.now = now
        if self.serial:
            for _ in range(2048):
                if not self.poll.poll(0):
                    break
                character = sys.stdin.read(1)
                if character in ("\n", "\r"):
                    line, self.line = self.line, ""
                    if line.startswith("~T"):
                        self.accept(line[2:])
                elif len(self.line) <= LINE_LIMIT + 2:
                    self.line += character
        if self.want and (self.beat is None or now - self.beat >= HEARTBEAT_MS):
            self.beat = now
            if len(self.outbox) < QUEUE_LIMIT:
                self.outbox.append(binascii.hexlify(HEARTBEAT).decode())

    def update(self):
        if self.serial and self.outbox:
            for value in self.outbox:
                sys.stdout.write("~R" + value + "\n")
            self.outbox = []

    def leave(self):
        self.seen = None
        self.inbox = []
        self.outbox = []

    def close(self):
        self.leave()
        self.want = False
