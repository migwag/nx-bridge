# Developing

For working on NXOSC_Reborn, building it, or distributing it. Users want
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
| `nx_protocol.py` | decode and OSC mapping; pure logic, no I/O |
| `nxosc_reborn.py` | the GUI |
| `nx_bridge.py` | the CLI |
| `validate.py`, `analyze.py` | verification harnesses |
| `fixtures/` | recorded reference captures |
| `scan.py`, `gatt.py`, `capture.py` | the tools used to reverse engineer it |
| `osc_listen.py` | records incoming OSC, for comparing against the original |
| `NXOSC_Reborn.spec` | PyInstaller recipe, incl. the macOS `Info.plist` |
| `build_app.sh`, `build_app.bat` | standalone builds |
| `sign_and_notarize.sh`, `entitlements.plist` | Developer ID signing |
| `make_bundle.sh` | macOS Bluetooth wrapper for running from source |
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

## Building standalone apps

```
./build_app.sh        # macOS/Linux -> dist/NXOSC_Reborn.app
build_app.bat         # Windows     -> dist\NXOSC_Reborn\NXOSC_Reborn.exe
```

PyInstaller cannot cross-compile; each platform must be built on itself. CI
(`.github/workflows/build.yml`) builds both on every push and uploads them as
artifacts, which is the practical way to get a Windows build from a Mac:

```
gh run download -n NXOSC_Reborn-windows
```

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
