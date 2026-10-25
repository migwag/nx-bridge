# NXOSC Reborn

Head tracking from the **Waves Nx Head Tracker** to **OSC**, on macOS, Windows
and Linux.

A replacement for the macOS-only Nxosc 1.0.5. The OSC output is identical, so
anything already listening to Nxosc keeps working with no changes.

- **NXOSC Reborn** -- the app, with a window
- `nx-bridge` -- the same thing as a command-line tool

## Getting it

**A ready-built app**, needing no Python: download it from the
[Actions tab](../../actions) (open the newest `build` run and grab the artifact
for your platform), or build it yourself -- see [DEVELOPING.md](DEVELOPING.md).

**Or run it from source**, with Python 3.10 or newer:

```
pip install -r requirements.txt
python nxosc_reborn.py
```

## Using it

Power the tracker on first -- it sleeps when idle. Make sure nothing else holds
its Bluetooth connection; quit the original Nxosc if it is running.

Press **Connect**. It finds the tracker and starts streaming. The window has
two tabs:

**Tracker** shows the device, battery level and live orientation -- quaternion,
Euler angles, and yaw / pitch / roll -- plus the stream rate and where OSC is
going. **Reset Center** makes your current head position the new centre; use it
once the tracker is on your head.

**OSC** chooses what gets sent, using the same profile format as Supperware's
[Bridgehead](https://supperware.net/headtracker/profile-txt/), so a
`profiles.txt` written for one works in the other.

Pick a profile from the menu, or edit the fields directly:

| Field | Example |
|---|---|
| OSC address | `/[yaw,pitch,roll]` or `/SceneRotator/[yaw,pitch,roll]` |
| Parameters | `yaw:1,pitch:1,roll:1` |
| Destinations | `local 8000`, one per line |

A **bracketed** address sends one message per name -- `/[yaw,pitch,roll]`
becomes `/yaw`, `/pitch` and `/roll`, which a DAW can learn. An address with
no brackets, like `/ypr`, sends a single message carrying all the values.

Parameters are `yaw`, `pitch`, `roll`, or the quaternion components `qw`, `qx`,
`qy`, `qz` -- angles or quaternion, not both. Angles are degrees unless you
add a suffix: `:r` radians, `:1` maps to -1..1, `:0` maps to 0..1. A leading
`-` reverses a value, and each trailing `_` adds 90 degrees, so `-yaw__` is
reversed yaw plus 180. `0` pads an unused slot and `s:text` sends a constant
string.

**Show File** reveals your `profiles.txt`; edit it and press **Reload**. Any
mistakes are reported in the panel rather than silently ignored.

Settings are remembered between runs.

### Command line

```
python nx_bridge.py                             # localhost:8000, as Nxosc
python nx_bridge.py --list                       # list nearby trackers
python nx_bridge.py --host 10.0.0.5 --port 9000
python nx_bridge.py --recenter                   # reset centre on connect
```

`--help` lists the rest. Ctrl-C to stop.

## OSC output

50 Hz, five messages per frame, all float32 -- the same as Nxosc 1.0.5:

| Address | Values | Meaning |
|---|---|---|
| `/nxosc/quaternion` | 4 | x, y, z, w -- a unit quaternion |
| `/nxosc/xyz` | 3 | Euler angles, degrees |
| `/SceneRotator/yaw` | 1 | degrees |
| `/SceneRotator/pitch` | 1 | degrees |
| `/SceneRotator/roll` | 1 | degrees |

`/SceneRotator/*` follows the IEM SceneRotator convention, which is what
SceneRotator-compatible binauralisers and rotators expect. Because the output
matches Nxosc exactly, anything that worked with Nxosc works here.

Angles can be switched to radians in the OSC tab.

## If something goes wrong

**No tracker found.** It powers itself off when idle -- wake it and try again.
Only one program can hold the connection, so quit the original Nxosc first.

**Nothing arrives at the receiving end.** OSC is UDP and silent on failure.
Check the destination matches the receiver, and that the profile sends the
addresses it expects. If another program already listens on port 8000, point
one of them elsewhere.

**An angle moves the wrong way.** Conventions differ between tools. Put a `-`
in front of that parameter, for instance `-yaw,pitch,roll`.

**On macOS, running from source quits immediately with no message.** macOS
requires Bluetooth permission. Either grant it to your terminal under System
Settings > Privacy & Security > Bluetooth, or use the built app, which asks for
permission normally. ([DEVELOPING.md](DEVELOPING.md) has a third option.)

**A tracker address from one computer does not work on another.** macOS
identifies Bluetooth devices with a per-machine ID, so `--address` values are
not portable. Leave it out and let it scan.

## More

- [PROTOCOL.md](PROTOCOL.md) -- the tracker's Bluetooth protocol, documented
- [DEVELOPING.md](DEVELOPING.md) -- building, testing, signing, extending

The protocol is closed and undocumented; it was reverse engineered for
interoperability and checked against the original across 3628 recorded frames,
which it reproduces to within 8e-6 degrees.
