Head tracking from the **Waves Nx Head Tracker** to **OSC** — on macOS and
Windows, and most likely Linux.

Follows the Supperware/Bridgehead convention, which is the de facto standard
for head tracking over OSC, so a `profiles.txt` moves between the two
applications unchanged. Coming from Nxosc 1.0.5, note that yaw and pitch run
the opposite way and quaternion components are named Supperware's way — the
README explains how to get the old behaviour back.

### What's new in 0.9.4

**The inbound control port now listens on this machine only.** If you use
`rx=` in `profiles.txt` to recenter from other software, it previously
accepted commands from anywhere on the network, with nothing to authenticate
against -- anyone able to reach the port could interrupt the stream or move
your orientation reference. To accept commands from elsewhere, give an
address as well as a port: `rx=0.0.0.0 9010` for any interface, or a specific
address to limit it.

**A malformed profile can no longer hang the window.** A parameter with a very
long run of underscores made the parser backtrack for seconds. It is now
parsed in a single pass, with a length limit.

Both came from a security review. The README also now describes `rx=`, which
it had never mentioned.

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
