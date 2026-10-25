# Developing

For working on NXOSC Reborn, building it, or distributing it. Users want
[README.md](README.md); the protocol itself is in [PROTOCOL.md](PROTOCOL.md).

## Setup

```
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Two runtime dependencies, `bleak` and `python-osc`. The GUI uses Tkinter from
the standard library, so there is nothing extra to install for it.
`requirements-dev.txt` adds PyInstaller, needed only for building.

## Testing without hardware

The fixtures are real captures, so both harnesses are genuine tests of the
decode and run anywhere:

```
./.venv/bin/python validate.py    # 3628 frames recorded from Nxosc 1.0.5
./.venv/bin/python analyze.py     # 1004 raw packets, at rest
```

`validate.py` is the important one. Nxosc emits its quaternion and its Euler
angles in the same callback, so its own output is the ground truth: feeding its
quaternion through our math must reproduce its angles. It prints
`RESULT: EXACT MATCH` when the maximum error is under a thousandth of a degree
(it is currently 8e-6 -- float32 rounding). **Run it after any change to the
math.** CI runs it on macOS and Windows for every push.

## Layout

| File | Purpose |
|---|---|
| `nx_protocol.py` | packet decode; pure logic, no I/O |
| `nx_profile.py` | Bridgehead profile.txt parsing and message building |
| `profiles.txt` | profiles shipped with the app, seeded on first run |
| `nxosc_reborn.py` | the GUI |
| `nx_bridge.py` | the CLI |
| `validate.py`, `analyze.py` | verification harnesses |
| `fixtures/` | recorded reference captures |
| `scan.py`, `gatt.py`, `capture.py` | the tools used to reverse engineer it |
| `osc_listen.py` | records incoming OSC, for comparing against the original |
| `check_convention.py` | measures our angle signs against Bridgehead's spec |
| `osc_sweep.py` | sends a synthetic single-axis rotation, no tracker needed |
| `NXOSC_Reborn.spec` | PyInstaller recipe, incl. the macOS `Info.plist` |
| `build_app.sh`, `build_app.bat` | standalone builds |
| `sign_and_notarize.sh`, `entitlements.plist` | Developer ID signing |
| `make_icon_art.py` | draws `icon.png` from code, stdlib only |
| `icon.png` | icon source art; `make_icons.sh` converts it |
| `make_icons.sh` | generates the `.icns`, `.ico` and window icon |
| `make_bundle.sh` | macOS Bluetooth wrapper for running from source |
| `macos_menubar.py` | the menu bar extra; a no-op off macOS |
| `nxboot.py`, `bridge_run.py`, `gui_run.py` | glue for that wrapper |

`gatt.py` and `capture.py` take a tracker address from `$NX_ADDR`.

## Extending

`nx_protocol.compute()` returns every derived value, and
`nx_protocol.osc_messages()` is the single place deciding what goes on the
wire. Change either and the GUI, the CLI and anything else importing the module
all follow. `decode_packet()` returns the raw unit quaternion if you would
rather do your own math.

Message *keys* are fixed because downstream tools depend on the meaning;
addresses are only defaults and can be renamed at runtime.

`apply_transform()` reorders, negates and offsets one message's values.
`order[i]` names the source component for output slot `i`, so `[3, 0, 1, 2]`
turns xyzw into wxyz. Offsets and wrapping apply only to keys in `ANGLE_KEYS`.
A config whose transform length no longer matches its message is discarded on
load, so adding a component to a message cannot break an existing install.

## Profiles

The GUI builds its OSC output from a Supperware Bridgehead profile
([format](https://supperware.net/headtracker/profile-txt/)), parsed by
`nx_profile.py`. `parse_profiles()` collects errors rather than raising, so
one bad profile does not hide the others, and the GUI shows them.

The active profile is always built from the three fields in the OSC tab; the
drop-down only fills them in. That keeps one code path whether the profile
came from the file or was typed.

On first run the shipped `profiles.txt` is copied to the config directory
beside `config.json`, and that copy is what the app reads afterwards.

Known gaps against Bridgehead:

- `rx=` and `raw=` lines are parsed and ignored, so a Bridgehead file loads,
  but incoming control messages (`/zero`, `/travel`, `/connect`) and raw
  sensor output are not implemented.
- Angle sign conventions are inherited from Nxosc, which need not agree with
  Bridgehead's. `check_convention.py` measures ours against Bridgehead's
  documented directions and prints the parameter line that reconciles them.
  Note that Nxosc compatibility and Bridgehead compatibility may be mutually
  exclusive per axis -- changing a shipped default picks a side.

`nx_protocol.osc_messages()` still produces the original fixed five-message
Nxosc output. The CLI uses it and `validate.py` checks it, so the verified
path stays verified; the GUI no longer goes through it.

## Plugin conventions

There is no single correct orientation convention: binauralisers disagree,
and a profile that is right for one is wrong for another. APL Virtuoso and
Audio Brewers want different things from the same tracker. This is why
profiles are per-receiver -- the answer is a profile per plugin, not a global
frame.

`osc_sweep.py` identifies what a plugin expects without involving the
tracker. It sends a clean synthetic rotation about one axis at a time, so
you watch the plugin rather than your own head:

    python3 osc_sweep.py --axis yaw
    python3 osc_sweep.py --axis pitch --params qw,qx,qy,qz --address /quaternion

Run it once per axis and note which axis the plugin moves and in which
direction. That gives the permutation and signs directly, which you then
write as a profile named for that plugin.

## Smoothing and send rate

`nx_protocol.Smoother` low-passes the **quaternion**, not the angles.
Filtering yaw as a number would swing it the long way round whenever it
crosses +-180 degrees; filtering the quaternion avoids that and smooths every
derived value consistently. It blends with normalised lerp -- close enough to
slerp at a 50 Hz step, and far cheaper -- and flips the sign of the incoming
quaternion when the dot product is negative, since q and -q are the same
rotation and the filter would otherwise lurch the long way.

`tau` is the time constant in seconds; zero is a pass-through. One tau follows
about 63% of a step, which the tests assert.

The send rate thins only the sending. The filter sees every packet, so a lower
rate low-passes the data instead of aliasing it. Both live on the worker, set
through `set_output()`.

These are app settings rather than profile fields: Bridgehead's format has no
place for them, and inventing one would mean our profiles.txt no longer loaded
in Bridgehead.

## The menu bar extra

`macos_menubar.py` wraps an `NSStatusItem` through pyobjc, which bleak
already depends on for CoreBluetooth, so it costs no new dependency. Tk's
event loop on macOS is Cocoa-based and pumps `NSApplication`, which is why a
status item created from Python receives its clicks without a second run
loop.

Hiding the Dock icon is `setActivationPolicy_`: `Accessory` drops the Dock
tile and the application menu, `Regular` restores them. The window's close
button withdraws the window and switches to Accessory; Show Window reverses
both and re-activates, which is needed or the window comes back behind
whatever has focus.

Every call fails soft. The extra is a convenience, and if AppKit is missing
or an API changes, the app should still run -- `available()` returns False
off macOS and the close button goes back to quitting.

## Bluetooth on each platform

**macOS** needs the permission dance below. **Windows** needs nothing: bleak
uses WinRT, and the tracker does not have to be paired in Bluetooth settings
first -- scanning and connecting behave as they do on macOS. **Linux** should
work from source through bleak's BlueZ backend over D-Bus, with Tkinter for
the GUI, but nobody has run it yet; treat it as unverified.

## macOS Bluetooth permission

CoreBluetooth terminates any process without
`NSBluetoothAlwaysUsageDescription` in an `Info.plist` -- SIGABRT, no error
message. Three ways around it:

1. Grant Bluetooth to your terminal under System Settings > Privacy &
   Security > Bluetooth. Simplest while developing.
2. Use a built app. `NXOSC_Reborn.spec` puts the key in the bundle's own
   `Info.plist`, so it just prompts.
3. `./make_bundle.sh` builds `NxTracker.app`, a wrapper around the python.org
   `Python.app` stub, for running scripts from source:

       open -a "$PWD/NxTracker.app" --args "$PWD/gui_run.py"
       open -a "$PWD/NxTracker.app" --args "$PWD/bridge_run.py" --port 8000

   Output goes to `gui.log` / `bridge.log`, as a bundle launched this way has
   no terminal attached.

One subtlety behind option 3: macOS attributes the permission to the
*responsible process*, not the one making the call. A bundle spawned as a child
of another process inherits that parent's missing permission, which is why it
must be launched through LaunchServices (`open`). A bundle launched this way
also gets a read-only working directory, so scripts write output to absolute
paths.

## Icons

The icon is drawn from source. `make_icon_art.py` renders `icon.png` using
signed distance fields and writes the PNG by hand, so it needs nothing but the
standard library -- edit the palette and geometry constants at the top:

```
python3 make_icon_art.py            # redraw icon.png
```

To use different artwork instead, just replace `icon.png` with any square PNG
(1024x1024 with transparency is ideal). Either way, convert it with:

```
./make_icons.sh          # or: ./make_icons.sh path/to/your.png
```

That writes three committed files, so Windows and Linux builds need no icon
tooling:

| File | Used for |
|---|---|
| `NXOSC_Reborn.icns` | the macOS app and its Dock tile |
| `NXOSC_Reborn.ico` | the Windows executable |
| `icon_256.png` | the window icon, on Windows and Linux |

Rebuild with `./build_app.sh` to pick them up. The script needs macOS, since it
uses `sips` and `iconutil`; the `.ico` is assembled directly from PNGs, which
is legal since Vista, so no image library is involved.

macOS caches icons aggressively. If the Dock shows the old one after a rebuild,
`touch dist/NXOSC_Reborn.app` or log out and back in.

## Building standalone apps

```
./build_app.sh        # macOS/Linux -> "dist/NXOSC Reborn.app"
build_app.bat         # Windows     -> dist\NXOSC_Reborn\NXOSC_Reborn.exe
```

The macOS bundle is named "NXOSC Reborn.app" with a space, since that is the
app's name. Everything internal -- the executable inside it, the source files,
the spec, the config directory, CI artifact names -- keeps the underscore.

PyInstaller cannot cross-compile; each platform must be built on itself. CI
(`.github/workflows/build.yml`) builds both on every push and uploads them as
artifacts, which is the practical way to get a Windows build from a Mac:

```
gh run download -n NXOSC_Reborn-windows
```

Move the build to Windows as a **zip, and extract it there**. Unpacking on
macOS and copying the folder across breaks it -- the exe starts and then
reports "Failed to load Python DLL", because something in `_internal` does
not survive the trip. On Windows, unblock the zip first (right-click >
Properties > Unblock) or the DLLs inside may be blocked. Running the exe
from inside the zip viewer fails the same way, since only that one file is
extracted and `_internal` is left behind.

The spec forces bleak's backend in explicitly (`collect_submodules`, plus
`CoreBluetooth`/`objc`/`libdispatch` on macOS and `winrt` on Windows). bleak
selects its backend at runtime, so PyInstaller's static analysis misses it and
you get an app that launches fine and then fails the moment you press Connect.

Builds are for the architecture of the build machine. Covering both Apple
Silicon and Intel needs a `universal2` Python, or one build each.

## Signing for distribution

A build is ad-hoc signed, which runs on the machine that made it and nowhere
else -- Gatekeeper refuses it elsewhere. With a paid Apple Developer account:

```
./sign_and_notarize.sh
```

That signs every nested binary inside-out (Apple deprecates `--deep`, which
also applies the wrong entitlements to nested code), applies the hardened
runtime, submits to Apple, staples the ticket, and verifies with `spctl` the
way Gatekeeper will. `SKIP_NOTARIZE=1` signs without uploading.

Two one-time setup steps, both involving credentials:

1. A *Developer ID Application* certificate: Xcode > Settings > Accounts >
   Manage Certificates. Confirm with
   `security find-identity -v -p codesigning`.
2. Notarisation credentials in the keychain, so no password appears on a
   command line:

       xcrun notarytool store-credentials "nxosc-notary" \
         --apple-id "you@example.com" --team-id "TEAMID"

   It prompts for an app-specific password from appleid.apple.com. Everything
   afterwards refers to the profile name.

`entitlements.plist` grants `allow-unsigned-executable-memory` (CPython writes
executable memory via libffi) and `disable-library-validation` (PyInstaller
ships ~62 libraries that are not all team-signed). Both are required: without
them the app notarises successfully and then crashes on launch.

Signatures do not need renewing. `codesign --timestamp` embeds a trusted
timestamp, so a signed build keeps working after the certificate expires, and
notarisation tickets do not expire. The certificate and membership are only
needed to sign *new* builds. Note this does not extend to `.pkg` installers,
which are checked at install time and must be re-signed -- a reason to keep
distributing a zipped `.app`.

Windows needs no signing to run, though SmartScreen may warn on first launch.
