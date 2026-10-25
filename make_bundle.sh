#!/bin/zsh
# Build NxTracker.app -- a minimal wrapper that lets a Python script use
# CoreBluetooth on macOS. Needed because macOS aborts any process that touches
# Bluetooth without NSBluetoothAlwaysUsageDescription in an Info.plist.
#
#   ./make_bundle.sh
#   open -a "$PWD/NxTracker.app" --args "$PWD/nx_bridge.py" --port 8000
#
# macOS only, and not needed at all on Windows or Linux.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
STUB="$(python3 -c 'import sys,os;print(os.path.join(sys.prefix,"Resources","Python.app"))')"
[ -d "$STUB" ] || STUB="$(python3 -c 'import sys,os;print(os.path.join(sys.base_prefix,"Resources","Python.app"))')"
if [ ! -d "$STUB" ]; then
  echo "Could not find the Python.app stub (looked in $STUB)." >&2
  echo "This needs a python.org framework build of Python." >&2
  exit 1
fi
APP="$HERE/NxTracker.app"
rm -rf "$APP"; cp -R "$STUB" "$APP"
PL="$APP/Contents/Info.plist"
DESC="Reads orientation data from the Waves Nx Head Tracker over Bluetooth LE."
/usr/libexec/PlistBuddy -c 'Delete :CFBundleIdentifier' "$PL" 2>/dev/null || true
/usr/libexec/PlistBuddy \
  -c 'Add :CFBundleIdentifier string cc.wagner.nxtracker' \
  -c "Add :NSBluetoothAlwaysUsageDescription string \"$DESC\"" \
  -c "Add :NSBluetoothPeripheralUsageDescription string \"$DESC\"" "$PL" >/dev/null
/usr/libexec/PlistBuddy -c 'Set :CFBundleName NxTracker' "$PL" >/dev/null 2>&1 || true
codesign --force --sign - --identifier cc.wagner.nxtracker "$APP"
echo "built $APP"
