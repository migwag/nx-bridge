# nx-bridge / NXOSC_Reborn

Waves Nx Head Tracker to OSC, on **macOS, Windows and Linux** -- as a GUI
(`NXOSC_Reborn`) or a CLI (`nx-bridge`).

A maintainable replacement for the macOS-only [Nxosc](https://www.audiooo.com/)
1.0.5. The OSC output is byte-for-byte compatible with the original, so
anything already listening to Nxosc works unchanged.

## Install

```
pip install -r requirements.txt
```

## Use -- GUI

```
python nxosc_reborn.py
```

Two tabs, following the original Nxosc layout:

- **Tracker** -- Connect/Disconnect, device and battery, live quaternion,
  Euler xyz and yaw/pitch/roll readouts, and **Reset Center** (the original's
  name for recentering). A status line shows the stream rate and destination.
- **OSC** -- OSC IP and port, degrees or radians, and a per-message row with a
  checkbox and an editable address, so you can rename or mute any of the five
  messages. **Restore Nxosc Defaults** puts everything back to byte-compatible
  output. Settings persist between runs.

Press Connect and it scans; with one tracker in range it connects straight
away, with several it offers a picker (the original's "Device Scan" sheet).

## Use -- CLI

```
python nx_bridge.py --list                      # find the tracker
python nx_bridge.py                             # Nxosc defaults: 127.0.0.1:8000
python nx_bridge.py --host 10.0.0.5 --port 9000
python nx_bridge.py --recenter                  # recenter on connect
```

Power the tracker on and make sure nothing else holds its BLE connection --
quit Nxosc first if it is running.

## OSC output

50 Hz, five messages per frame, all float32 -- identical to Nxosc 1.0.5:

| Address | Args | Meaning |
|---|---|---|
| `/nxosc/quaternion` | 4 | x, y, z, w (unit quaternion) |
| `/nxosc/xyz` | 3 | Euler degrees |
| `/SceneRotator/yaw` | 1 | degrees, IEM SceneRotator convention |
| `/SceneRotator/pitch` | 1 | degrees |
| `/SceneRotator/roll` | 1 | degrees |

## Building a standalone app

No Python install needed on the target machine.

```
./build_app.sh        # macOS/Linux  -> dist/NXOSC_Reborn.app
build_app.bat         # Windows      -> dist\NXOSC_Reborn\NXOSC_Reborn.exe
```

PyInstaller **cannot cross-compile**: a Windows .exe has to be built on
Windows. If you only have a Mac, push to GitHub and let
`.github/workflows/build.yml` build both -- it also runs `validate.py` and
`analyze.py`, which need no hardware, so CI verifies the protocol decode
rather than just that it compiles.

The macOS bundle is the better answer to the Bluetooth-permission problem:
`NXOSC_Reborn.spec` writes `NSBluetoothAlwaysUsageDescription` into the app's
own `Info.plist`, so the frozen app gets a normal permission prompt and needs
none of the `NxTracker.app` wrapper described below.

Two caveats:

- The build is **ad-hoc signed**, which is fine on the machine that built it.
  Handing it to anyone else needs a Developer ID signature and notarisation,
  or Gatekeeper will refuse to open it. `build_app.sh` prints the commands.
- It is built for the **architecture of the build machine**. Running on both
  Apple Silicon and Intel needs a `universal2` Python, or one build each.

## Platform notes

**macOS** will kill any process that touches CoreBluetooth without an
`NSBluetoothAlwaysUsageDescription` in an `Info.plist` -- a bare
`python nx_bridge.py` aborts with SIGABRT and no error message. Two options:

- Run it from a terminal you have granted Bluetooth access under
  System Settings -> Privacy & Security -> Bluetooth.
- Or run it inside an app bundle that declares the key. `./make_bundle.sh`
  builds one from the python.org `Python.app` stub:

      ./make_bundle.sh
      open -a "$PWD/NxTracker.app" --args "$PWD/gui_run.py"            # GUI
      open -a "$PWD/NxTracker.app" --args "$PWD/bridge_run.py" --port 8000

  Output goes to `bridge.log`, since a bundle launched this way has no terminal.

Note macOS attributes the Bluetooth permission to the *responsible process*,
so a bundle launched as a child of another process inherits that parent's
(missing) permission. Launching through LaunchServices (`open`) avoids this.

**Windows** needs none of that -- bleak uses WinRT and the device pairs as a
normal BLE peripheral.

**Addresses differ by platform.** macOS reports an opaque per-host UUID rather
than a MAC address, so an `--address` value is not portable between machines.

## Files

| File | Purpose |
|---|---|
| `nx_protocol.py` | pure decode logic, no I/O -- the reusable core |
| `nxosc_reborn.py` | the GUI |
| `nx_bridge.py` | CLI: BLE in, OSC out |
| `PROTOCOL.md` | full protocol documentation and how it was derived |
| `scan.py`, `gatt.py`, `capture.py` | the reverse-engineering tools |
| `osc_listen.py` | records incoming OSC, for comparing against the original |
| `validate.py`, `analyze.py` | verification harnesses (run with no args) |
| `fixtures/` | captured reference data, used by the harnesses |
| `NXOSC_Reborn.spec` | PyInstaller recipe, incl. the macOS `Info.plist` |
| `build_app.sh`, `build_app.bat` | one-shot standalone builds |
| `make_bundle.sh` | macOS Bluetooth wrapper, for running from source |
| `nxboot.py`, `bridge_run.py`, `gui_run.py` | glue for running under that wrapper |

## Setup

```
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./make_bundle.sh          # macOS only
```

Check it works without any hardware:

```
./.venv/bin/python validate.py    # replays 3628 recorded Nxosc frames
./.venv/bin/python analyze.py     # replays 1004 recorded raw packets
```

## Extending

`nx_protocol.osc_messages()` is the single place that decides what goes out,
and `compute()` returns every derived value so callers never repeat the math.
Add an address, change a convention, or apply smoothing there and the GUI, the
CLI and anything else importing the module all pick it up. `decode_packet()` hands you
the raw unit quaternion if you would rather do your own math.

## Provenance

Reverse engineered from Nxosc 1.0.5 for interoperability, and verified against
it: 3628 captured frames reproduce to within 8e-6 degrees. See `PROTOCOL.md`.
