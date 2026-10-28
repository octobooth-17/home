# Attendee Chat

Attendee Chat automatically identifies a nearby badge and sends text and six emoji after its owner accepts a chat request.

## Requirements and range

Both people need a Universe 2026 badge with `badgeware.link` firmware and this
app installed. No Wi-Fi, server, GitHub token, or extra hardware is required.
Use **Request chat** on one badge and **Ready to receive** on
the other, then hold the badges **back-to-back** as in Contacts and Pong.
Connection and ongoing range depend on the badge radio and surroundings;
**100 feet is not guaranteed**. Wi-Fi/venue-wide messaging is not implemented.

## Usage

1. Open the app. No identity keyboard is needed: it uses the badge's
   configured `GITHUB_USERNAME`, then the `login` in `/state/badge_user.json`,
   or a device ID derived from `machine.unique_id()` if neither is configured.
   The simulator uses an explicitly simulated badge ID when unconfigured.
   This app does not fetch or verify a GitHub account or change badge settings.
2. The sender chooses **Request chat**. The other person chooses
   **Ready to receive**. Hold their badges **back-to-back**. The nearby peer's
   identity is detected automatically; no target handle needs to be typed.
   The first connected peer is used, not an attendee selected across the venue.
3. The sender sees **Waiting for their acceptance**. The recipient checks
   the displayed sender ID and presses **Select** to accept or **Back** to
   decline. Choosing Ready to receive is not itself consent to messages.
   Invitations expire after 30 seconds once linked.
4. After the acceptance handshake, both screens show a **Chat accepted!**
   notification and open the conversation. No text or emoji can be exchanged
   before acceptance. Confirm the person in front of you before accepting.
5. In chat, **Select** opens the text keyboard. Choose **Aa** for uppercase,
   **Space** for a space, **Del** to delete, and **Send** to send up to 96
   printable ASCII characters. **Close** (or **Back**) returns to the chat
   while retaining the draft.
6. Choose **Emoji** on the keyboard (or press **Menu** in chat) to open six
   illustrated emoji: Smile, Heart, Thumbs up, Wave, Star, and Rocket. Use
   arrows to choose and **Select** to send.
7. **Up/Down** scroll through chat history. **Back**, then **Select**, ends the
   chat; **Back** cancels the end-chat confirmation. **Home** always exits.

One outgoing message at a time is allowed. A message shows **sending** until
the other badge acknowledges receipt, then **delivered** (not a read receipt).
Retries do not duplicate received messages. After 12 seconds without an
acknowledgment it becomes **unconfirmed**: it may have arrived, so avoid
blindly resending it. A full radio queue or malformed packet ends the session
with a visible error instead of falsely claiming success.

## Privacy and consent

Nearby IDs are **self-reported, not authenticated GitHub identities**.
Confirm the ID with the person in front of you; another badge can claim
someone else's ID. A badge ID is not a GitHub account. This is not an authenticated or end-to-end encrypted
messenger, and is unsuitable for sensitive information.

No text or emoji is sent or accepted before consent for the current session.
Declining, timing out, ending, disconnecting, or exiting clears acceptance.
The next connection requires a fresh invitation. This app saves no state;
it reads the badge's configured identity at launch. The last 24 messages and drafts remain in RAM, are
cleared when returning home after a session, and are lost on exit. Radio peers
can see self-reported IDs before acceptance.

## Testing with one badge

Choose **Demo: send request** to act as the sender: a simulated attendee
receives your request and accepts after a short wait. You see the waiting
status and acceptance notification. Choose **Demo: receive request** to act
as the recipient: **Select** accepts the simulated request and **Back**
declines. After accepting, try the text keyboard and all six emoji.
The simulated attendee echoes messages and shows delivery confirmations.
Automatic acceptance exists only in the labelled sender demo, not real chat.

Every demo screen is labelled **DEMO / NO RADIO**. This mode does not open a
radio link or send anything to another person, and works without
`badgeware.link`. It verifies UI and protocol behavior on one badge, **not**
real RF delivery, connection range, or the presence of a second attendee.
Return home or exit to discard the demo session. Real invitations remain
separate and always require fresh acceptance.

### USB test: simulator and one badge

The home item **Connection** switches between **Nearby radio** and **USB
test**. In USB test, packets travel over the USB cable through a relay on the
computer instead of the radio, so the local preview simulator can chat with a
badge connected to the same computer. The simulator starts in USB test (it
has no radio); the badge starts in Nearby radio.

1. Install the app on the badge, open it, and select **Connection** until it
   shows **USB test**. Close any `mpremote`, Thonny, or serial tabs.
2. Start the local simulator preview and note its URL and agent token.
3. Run `python tools/chat_usb_relay.py --sim-url <url> --token <token>`
   (`--port COMn` if auto-detection fails). It needs `pyserial`, which
   `mpremote` installs. Leave it running; Ctrl-C stops it.
4. Choose **Request chat** on one side and **Ready to receive** on the other,
   then accept, send text, and send emoji as usual.

Screens are labelled **USB TEST / NO RADIO**. Consent still applies. This mode
tests the chat protocol and screens on two devices, **not** the radio, range,
or a second attendee. While the relay runs, it owns the badge's serial port.

## Validation and physical checklist

From the repository root, run:

```powershell
python -m unittest discover -s tests -p "test_attendee_chat*.py"
python .github\skills\hyb26-skill\scripts\validate_app.py badge\apps\attendee_chat
python .github\scripts\validate_app_readmes.py badge\apps
```

The host tests use two linked protocol peers and a stub badge runtime; they
cannot establish RF range, firmware timing, or the real appearance of the UI.
The web simulator does not implement badge-to-badge radio. Unsupported firmware
shows a radio-unavailable message rather than pretending to connect.

For an in-app preview, open Attendee Chat in the Badge Simulator (or its browser
preview), then select either **Demo** option. This runs the
same app and offline peer, not a separate web mock-up. Use the on-screen badge
controls or keyboard arrows and Enter; **U** is Menu and **K** is Back in the
browser simulator. The browser highlights **Demo: send request** by default.
Real invitation options use **USB test** by default and require the computer
relay described above; **Nearby radio** is unavailable in the browser.
The app never silently substitutes a demo for a real attendee.

For a transient native check on one connected badge, discover its port with
`python -m mpremote devs`, then run (replace `COM16` with that port):

```powershell
python -m mpremote connect COM16 mount badge\apps\attendee_chat run tests\attendee_chat_hardware_probe.py
python -m mpremote connect COM16 reset
```

The probe renders the real UI, exercises the simulated invitation, text echo,
all six emoji and cleanup, then initializes the real firmware radio without a
peer. It does not install the app or save a handle. The final reset returns to
the normal menu. This does not verify two-badge communication or range.

On two real badges, verify automatic configured-handle and device-ID lookup,
request/receive, both-request and both-receive behavior, accept/decline and
timeout, the sender's acceptance notification, text and all six emoji in both directions, delivery confirmation,
disconnect/reinvite, Home/reopen, both orientations, keyboard readability, and
the custom launcher icon. Test increasing separation in the actual venue;
record the last reliable distance rather than assuming a range.

Install through USB Disk Mode following `hardware/USB_SERIAL.md`, including
the menu icon patch if needed. Do not copy real credentials into the app.
Regenerate the original icon and emoji artwork with
`python tools\build_chat_assets.py`.
