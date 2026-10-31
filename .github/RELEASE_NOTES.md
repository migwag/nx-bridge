Head tracking from the **Waves Nx Head Tracker** to **OSC** — on macOS and
Windows, and most likely Linux.

Follows the Supperware/Bridgehead convention, which is the de facto standard
for head tracking over OSC, so a `profiles.txt` moves between the two
applications unchanged. Coming from Nxosc 1.0.5, note that yaw and pitch run
the opposite way and quaternion components are named Supperware's way — the
README explains how to get the old behaviour back.

### What's new in 0.9.2

**Send rate fixed.** It was wrong at almost every setting, not just erratic:
asking for 30 Hz off a 50 Hz tracker delivered 25, and 25 delivered 20.6. The
requested rate is now delivered exactly. The Hz figure in the status line also
follows the setting as you change it, rather than averaging over the whole
session.

**Building from source.** `build_app.sh` now checks the Python you are
building with before it starts, and refuses with an explanation if the result
would be an app that dies the moment it launches. If one already does, both it
and DEVELOPING.md tell you how to see the real error.

Also: a note of thanks to Katsuhiro Chiba, whose Nxosc this follows.

### Download

- **macOS** — `NXOSC-Reborn-macOS.zip`
- **Windows** — `NXOSC-Reborn-Windows.zip`

Both are standalone; no Python needed.

**Linux** has no prebuilt binary, but the source is expected to work — bleak
uses BlueZ and the GUI is Tkinter. Untested, so reports are welcome.

**macOS.** The app is not signed by an identified developer yet, so the first
launch is blocked. Open it once, dismiss the warning, then go to System
Settings → Privacy & Security, scroll to the bottom and click **Open Anyway**.

**Windows.** Extract the zip **on the Windows machine** and keep
`NXOSC_Reborn.exe` together with the `_internal` folder beside it. SmartScreen
may warn on first run: More info → Run anyway.

### This is a beta

It works, and the protocol decode is verified automatically on every build
against 3628 frames recorded from the original Nxosc. But it has been tested by
very few people, on few setups. Please report what breaks.
