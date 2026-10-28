"""Relay attendee_chat USB test packets between a connected badge and the simulator.

Run the attendee_chat app on the badge and in the local preview simulator, set
Connection to "USB test" on both, then start this script:

    python tools/chat_usb_relay.py --sim-url http://127.0.0.1:PORT --token TOKEN

The badge prints "~R<hex>" lines and reads "~T<hex>" lines over USB serial; the
simulator side is reached through the preview server's /_agent exec endpoint.
This tests the chat protocol and screens, not the badge radio or its range.
"""

import argparse
import json
import re
import sys
import time
import urllib.request

import serial
from serial.tools import list_ports

HEX = re.compile(r"^[0-9a-f]{2,256}$")
EXCHANGE = (
    "import json\n"
    "_l = app.link if getattr(app, 'usb', False) else None\n"
    "print('~X' + json.dumps(_l.exchange({incoming}) "
    "if _l is not None and hasattr(_l, 'exchange') else None))\n"
)


def find_port():
    for port in list_ports.comports():
        if port.vid == 0x2E8A and port.pid == 0x1101:
            return port.device
    raise SystemExit("No badge found (USB 2e8a:1101). Pass --port.")


def connect(requested):
    while True:
        try:
            port = requested or find_port()
            # Opening with DTR/RTS low avoids resetting the running app.
            link = serial.Serial()
            link.port, link.baudrate, link.timeout = port, 115200, 0
            link.dtr = link.rts = False
            link.open()
            return link
        except (SystemExit, serial.SerialException):
            time.sleep(1)


def simulator_exchange(url, token, incoming):
    body = json.dumps({"action": "exec",
                       "code": EXCHANGE.format(incoming=json.dumps(incoming))}).encode()
    request = urllib.request.Request(url.rstrip("/") + "/_agent", data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "X-Preview-Token": token})
    with urllib.request.urlopen(request, timeout=5) as response:
        result = json.load(response)
    for line in reversed(str(result.get("output", "")).splitlines()):
        if line.startswith("~X"):
            value = json.loads(line[2:])
            return [item for item in value or [] if isinstance(item, str) and HEX.match(item)]
    raise RuntimeError("simulator did not answer: " + json.dumps(result)[:200])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", help="badge serial port (default: auto-detect)")
    parser.add_argument("--sim-url", required=True, help="preview server URL")
    parser.add_argument("--token", required=True, help="preview server agent token")
    parser.add_argument("--interval", type=float, default=0.08)
    args = parser.parse_args()

    link = connect(args.port)
    print("relay: badge", link.port, "<-> simulator", args.sim_url, flush=True)
    buffer = b""
    counts = {"badge": 0, "simulator": 0}
    beats = {"badge": 0, "simulator": 0}
    reported = time.monotonic()
    failures = 0
    while True:
        try:
            buffer += link.read(4096)
        except serial.SerialException as error:
            # The badge re-enumerates USB whenever it restarts (e.g. launching an app).
            print("relay: badge disconnected (%s); waiting for it to return..." % error,
                  flush=True)
            link.close()
            link = connect(args.port)
            print("relay: badge reconnected on", link.port, flush=True)
            buffer = b""
            continue
        incoming = []
        *lines, buffer = buffer.split(b"\n")
        buffer = buffer[-1024:]
        for raw in lines:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("~R") and HEX.match(line[2:]):
                incoming.append(line[2:])
            elif line:
                print("badge:", line, flush=True)
        try:
            outgoing = simulator_exchange(args.sim_url, args.token, incoming)
            failures = 0
        except Exception as error:  # keep relaying through simulator reloads
            failures += 1
            if failures in (1, 25) or failures % 250 == 0:
                print("relay: simulator unavailable:", error, flush=True)
            time.sleep(0.5)
            continue
        if outgoing:
            try:
                link.write("".join("~T%s\n" % value for value in outgoing).encode())
            except serial.SerialException:
                pass  # the next read notices the disconnect and reconnects
        for side, values in (("badge", incoming), ("simulator", outgoing)):
            data = [value for value in values if value != "50"]
            beats[side] += len(values) - len(data)
            if data:
                counts[side] += len(data)
                print("relay: %s -> %s packets (%d total)" % (side, len(data), counts[side]),
                      flush=True)
        if time.monotonic() - reported >= 5:
            reported = time.monotonic()
            print("relay: ready signals in last 5s - badge %d, simulator %d"
                  % (beats["badge"], beats["simulator"]), flush=True)
            beats = {"badge": 0, "simulator": 0}
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
