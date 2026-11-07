Head tracking from the **Waves Nx Head Tracker** to **OSC** — on macOS and
Windows, and most likely Linux.

Follows the Supperware/Bridgehead convention, which is the de facto standard
for head tracking over OSC, so a `profiles.txt` moves between the two
applications unchanged. Coming from Nxosc 1.0.5, note that yaw and pitch run
the opposite way and quaternion components are named Supperware's way — the
README explains how to get the old behaviour back.

### What's new in 0.9.3

**Recenter now levels pitch and roll as well as yaw.** The tracker's own reset
only touches yaw -- pitch and roll are measured against gravity, so there is
nothing in the device to reset -- which left a tracker mounted at an angle
reporting that angle forever. **Recenter in software**, on the Tracker tab,
levels all three. It is on by default for new installations; if you have run
an earlier version, tick it yourself, as your saved settings are left alone.

Recentering also no longer drags the smoothing filter across the jump it
deliberately creates.

**One name for it.** The button, the menu bar and the messages all say
*Recenter* now, instead of mixing that with *Reset Center*.

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
