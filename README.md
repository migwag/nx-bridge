# NXOSC Reborn

Head tracking from the **Waves Nx Head Tracker** to **OSC**, on macOS and
Windows.

### [Download the latest release →](../../releases/latest)

The Nx Head Tracker is a small Bluetooth device that clips to your headphones
and reports which way your head is pointing. This app reads it and sends that
orientation as OSC, so binaural and immersive tools can follow your head.

It replaces the macOS-only [Nxosc](https://www.audiooo.com/) 1.0.5, which was
last updated in 2017. The OSC output is identical, so anything already
listening to Nxosc keeps working. Beyond that it adds Windows support, a
profile system shared with Supperware's Bridgehead, smoothing, and a settable
send rate.

Unofficial and not affiliated with Waves Audio. The tracker's protocol is
closed; it was reverse engineered for interoperability and is documented in
[PROTOCOL.md](PROTOCOL.md).

---

## Install

Download the zip for your platform from the
[latest release](../../releases/latest). Nothing else is needed — Python is
not required.

### macOS

Unzip and drag **NXOSC Reborn** to Applications.

The app is not yet signed by an identified developer, so macOS blocks the
first launch:

1. Open it, and dismiss the warning.
2. Go to **System Settings → Privacy & Security**.
3. Scroll to the bottom and click **Open Anyway**.

You only do this once. macOS will also ask for **Bluetooth** permission the
first time you connect — that is required to read the tracker.

### Windows

Extract the zip **on the Windows machine**, not elsewhere, and keep
`NXOSC_Reborn.exe` together with the `_internal` folder beside it. Copying
the extracted folder from another computer, or launching the exe from inside
the zip viewer, gives "Failed to load Python DLL".

Pair the tracker in Windows Bluetooth settings first. SmartScreen may warn on
first run: **More info → Run anyway**.

---

## Using it

Switch the tracker on — it sleeps when idle — and make sure nothing else is
connected to it. Then press **Connect**.

The **Tracker** tab shows the device, its battery and live orientation, plus
the stream rate and where OSC is going. **Reset Center** makes your current
head position the new centre; use it once the tracker is on your head.

On macOS the app also lives in the menu bar. Closing the window leaves it
running and streaming, and the Dock icon disappears; the menu bar icon shows
whether data is flowing and offers **Show Window**, **Reset Center** and
**Quit**.

### Sending to your plugin

The **OSC** tab decides what gets sent. Different binauralisers expect
different things, so you pick a profile per plugin rather than hunting for
one universal setting. Several are included:

| Profile | For |
|---|---|
| SceneRotator | IEM-style `/SceneRotator/yaw,pitch,roll` |
| APL Virtuoso | `/Virtuoso/quat` |
| Audio Brewers | `/[yaw,pitch,roll]`, 0 to 1 |
| Nuendo (HeadPose) | `/head_pose`, seven floats |
| Yaw/Pitch/Roll, Quaternion, … | generic starting points |

Pick one from the menu, or edit the address, parameters and destination
directly.

The format is Supperware's, so a `profiles.txt` written for
[Bridgehead](https://supperware.net/headtracker/) works here unchanged, and
vice versa. **The syntax is documented at
[supperware.net/headtracker/profile-txt](https://supperware.net/headtracker/profile-txt/)**
— addresses, parameters, scaling suffixes, sign and rotation modifiers, and
destinations.

**Show File** opens your own `profiles.txt` so you can add to it; **Reload**
re-reads it. Mistakes are reported in the panel rather than ignored.

### Smoothing and send rate

**Smoothing** low-passes the orientation; the figure beside it is the time
constant in milliseconds. 40–80 ms takes the edge off without noticeable lag.

**Send rate** thins the output for receivers that cannot keep up with 50 Hz —
some plugins and DAWs cannot. `0` sends every packet. Smoothing still sees
every packet, so a lower rate filters the data rather than dropping samples.

Settings are remembered between runs.

---

## If something goes wrong

**No tracker found.** It powers itself off when idle — wake it and try again.
Only one program can hold the connection, so quit anything else using it.

**Nothing arrives.** OSC is UDP and silent on failure. Check the destination
matches what the receiver is listening on. If something else already has port
8000, move one of them.

**An angle moves the wrong way, or the wrong axis moves.** Conventions differ
between plugins. Put a `-` in front of a parameter to reverse it, or reorder
them, and save it as a profile for that plugin.

**The receiver stutters.** Lower the send rate. 25 Hz, even 10 Hz, is plenty
for head tracking.

---

## This is a beta

It works, and the protocol decode is verified automatically on every build
against 3628 frames recorded from the original app. But few people have run
it, on few setups. Bug reports are welcome — please say which plugin, which
platform, and what you expected.

Known gaps: the macOS and Windows builds are unsigned, so both show a warning
on first launch. Bridgehead's `rx=` and `raw=` lines are accepted but do
nothing. There is no Linux build, though the source runs there.

## Building it yourself

See [DEVELOPING.md](DEVELOPING.md) — building, the test harnesses, the macOS
signing pipeline, and how the protocol was worked out.

```
pip install -r requirements.txt
python nxosc_reborn.py
```

Needs Python 3.10 or newer. There is also a command-line version,
`nx_bridge.py`.
