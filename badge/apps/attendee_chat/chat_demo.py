"""An explicitly offline attendee for exercising one badge without a radio."""

import random

from chat_protocol import Chat, MAX_TEXT


class DemoLink:
    def __init__(self, peer, replies=None):
        self.peer = peer
        self.replies = replies

    def capacity(self):
        return 20

    def send(self, packet):
        message = self.peer.wire.receive(packet)
        if message is not None:
            previous = self.peer.received
            self.peer.receive(message)
            if self.replies is not None and self.peer.received > previous:
                self.replies.append((message[3], message[4]))
        return True


class Demo:
    def __init__(self, chat, requesting=False):
        self.chat = chat
        self.requesting = requesting
        chat.start("", "%08x%08x" % (random.getrandbits(32), random.getrandbits(32)),
                   request=requesting)
        name = "demo-attendee" if chat.username != "demo-attendee" else "demo-friend"
        self.peer = Chat(name)
        nonce = "%08x%08x" % (random.getrandbits(32), random.getrandbits(32))
        self.peer.start("" if requesting else chat.username, nonce)
        self.replies = []
        self.outgoing = DemoLink(self.peer, self.replies)
        self.incoming = DemoLink(chat)
        self.welcomed = False
        chat.connected()
        self.peer.connected()

    def pump(self, elapsed):
        self.peer.step(elapsed)
        self.chat.wire.flush(self.outgoing)
        self.peer.wire.flush(self.incoming)
        if self.requesting and self.peer.state == "incoming" and self.peer.age >= 1500:
            self.peer.accept()
        if self.peer.state == "active" and self.peer.pending is None:
            if not self.welcomed:
                self.peer.send("t", "Offline demo! Send text or an emoji and I will echo it.")
                self.welcomed = True
            elif self.replies:
                kind, value = self.replies.pop(0)
                if kind == "t":
                    value = "Demo echo: " + value[:MAX_TEXT - 11]
                self.peer.send(kind, value)
