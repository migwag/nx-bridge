Head tracking from the **Waves Nx Head Tracker** to **OSC**, on macOS and
Windows.

### Download

- **macOS** — `NXOSC-Reborn-macOS.zip`
- **Windows** — `NXOSC-Reborn-Windows.zip`

Both are standalone; no Python needed.

**macOS.** The app is not signed by an identified developer yet, so the first
launch is blocked. Open it once, dismiss the warning, then go to System
Settings → Privacy & Security, scroll to the bottom and click **Open Anyway**.

**Windows.** Extract the zip **on the Windows machine** and keep
`NXOSC_Reborn.exe` together with the `_internal` folder beside it. SmartScreen
may warn on first run: More info → Run anyway.

### This is a beta

It works, and the protocol decode is verified automatically on every build
against 3628 frames recorded from the original app. But it has been tested by
very few people, on few setups. Please report what breaks.
