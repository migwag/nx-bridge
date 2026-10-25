#!/bin/zsh
# Build a standalone NXOSC_Reborn for the CURRENT platform.
# PyInstaller cannot cross-compile -- run this on each OS you want a build for.
#
#   macOS   -> dist/NXOSC_Reborn.app
#   Windows -> dist\NXOSC_Reborn\NXOSC_Reborn.exe  (use build_app.bat)
#   Linux   -> dist/NXOSC_Reborn/NXOSC_Reborn
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PY="${PY:-./.venv/bin/python}"
"$PY" -m pip install --quiet -r requirements.txt -r requirements-dev.txt
"$PY" -m PyInstaller --noconfirm --clean NXOSC_Reborn.spec
echo
echo "built: $(ls -d dist/NXOSC_Reborn* | head -1)"
if [ "$(uname)" = "Darwin" ]; then
  echo
  echo "The bundle is ad-hoc signed, which is fine on this Mac. To share it,"
  echo "sign and notarise with a Developer ID or Gatekeeper will refuse it:"
  echo "  codesign --deep --force --options runtime --sign 'Developer ID Application: NAME (TEAMID)' dist/NXOSC_Reborn.app"
  echo "  xcrun notarytool submit --wait ..."
fi
