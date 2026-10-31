#!/bin/zsh
# Build a standalone NXOSC_Reborn for the CURRENT platform.
# PyInstaller cannot cross-compile -- run this on each OS you want a build for.
#
#   macOS   -> "dist/NXOSC Reborn.app"
#   Windows -> dist\NXOSC_Reborn\NXOSC_Reborn.exe  (use build_app.bat)
#   Linux   -> dist/NXOSC_Reborn/NXOSC_Reborn
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PY="${PY:-./.venv/bin/python}"

# Preflight. A build can succeed and still produce an app that dies the
# instant it launches -- the Dock icon flashes and nothing else happens --
# because PyInstaller bundles whatever Tk it finds, broken or not. Catch
# that here, where the message can be read, rather than in a silent crash.
"$PY" - <<'PREFLIGHT' || { echo "Preflight failed -- not building." >&2; exit 1; }
import sys, sysconfig
problems = []
try:
    import tkinter
    tkinter.Tk().destroy()
except Exception as exc:
    problems.append(f"Tkinter does not work in this Python: {type(exc).__name__}: {exc}")
if sys.platform == "darwin" and not sysconfig.get_config_var("PYTHONFRAMEWORK"):
    problems.append("this is not a framework build of Python; its Tk is often "
                    "unusable once bundled")
if sys.version_info < (3, 10):
    problems.append(f"Python {sys.version_info.major}.{sys.version_info.minor} "
                    "is too old; 3.10 or newer is needed")
if problems:
    print("\nThe built app would not start:\n", file=sys.stderr)
    for p in problems:
        print(f"  - {p}", file=sys.stderr)
    print("\nUse a python.org framework build (or Homebrew's python-tk), "
          "recreate the venv, and try again.\n", file=sys.stderr)
    raise SystemExit(1)
print(f"preflight ok: {sys.executable}")
PREFLIGHT

"$PY" -m pip install --quiet -r requirements.txt -r requirements-dev.txt
"$PY" -m PyInstaller --noconfirm --clean NXOSC_Reborn.spec
echo
echo "built: $(ls -d dist/NXOSC* | head -1)"
echo
echo "If it does not start -- Dock icon flashes, no window, no error --"
echo "run the binary inside the bundle to see why:"
if [ "$(uname)" = "Darwin" ]; then
  echo "  \"$(pwd)/dist/NXOSC Reborn.app/Contents/MacOS/NXOSC_Reborn\""
else
  echo "  ./dist/NXOSC_Reborn/NXOSC_Reborn"
fi
if [ "$(uname)" = "Darwin" ]; then
  echo
  echo "The bundle is ad-hoc signed, which is fine on this Mac. To share it,"
  echo "sign and notarise with a Developer ID or Gatekeeper will refuse it:"
  echo "  ./sign_and_notarize.sh"
  echo "  xcrun notarytool submit --wait ..."
fi
