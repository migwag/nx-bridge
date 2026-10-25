#!/bin/zsh
# Sign, notarise and staple dist/NXOSC_Reborn.app for distribution to other Macs.
#
# Prerequisites, both one-time and both yours to do:
#
#   1. A "Developer ID Application" certificate in your login keychain.
#      Xcode > Settings > Accounts > Manage Certificates > + > Developer ID Application
#      Verify with:  security find-identity -v -p codesigning
#
#   2. Notarisation credentials stored in the keychain, so no password ever has
#      to be passed on a command line:
#        xcrun notarytool store-credentials "nxosc-notary" \
#          --apple-id "you@example.com" --team-id "TEAMID"
#      It will prompt for an app-specific password (appleid.apple.com > Sign-In
#      and Security > App-Specific Passwords). An API key works too:
#        xcrun notarytool store-credentials "nxosc-notary" \
#          --key AuthKey_XXXX.p8 --key-id KEYID --issuer ISSUERID
#
# Then:
#   ./sign_and_notarize.sh                      # auto-detects the identity
#   IDENTITY="Developer ID Application: Name (TEAM)" ./sign_and_notarize.sh
#   PROFILE=other-profile ./sign_and_notarize.sh
#   SKIP_NOTARIZE=1 ./sign_and_notarize.sh      # sign only, no upload to Apple
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

APP="dist/NXOSC_Reborn.app"
PROFILE="${PROFILE:-nxosc-notary}"
ENTITLEMENTS="entitlements.plist"

[ -d "$APP" ] || { echo "No $APP -- run ./build_app.sh first." >&2; exit 1; }

# --- 1. identity -----------------------------------------------------------
if [ -z "$IDENTITY" ]; then
  IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null \
    | grep 'Developer ID Application' | head -1 \
    | sed -E 's/.*"(.*)".*/\1/')"
fi
if [ -z "$IDENTITY" ]; then
  cat >&2 <<MSG
No "Developer ID Application" identity found in the keychain.

Create one in Xcode > Settings > Accounts > Manage Certificates, then check:
  security find-identity -v -p codesigning

Until then the ad-hoc build in $APP runs on this Mac but nowhere else.
MSG
  exit 1
fi
echo "signing identity: $IDENTITY"

# --- 2. sign inside-out ----------------------------------------------------
# Apple deprecates --deep; sign every nested Mach-O first, then the bundle.
echo "signing nested binaries ..."
COUNT=0
while IFS= read -r f; do
  codesign --force --timestamp --options runtime \
           --entitlements "$ENTITLEMENTS" --sign "$IDENTITY" "$f" 2>/dev/null || true
  COUNT=$((COUNT+1))
done < <(find "$APP/Contents" -type f \( -name '*.so' -o -name '*.dylib' \) )
echo "  signed $COUNT libraries"

find "$APP/Contents/Frameworks" -maxdepth 1 -name '*.framework' -print0 2>/dev/null \
  | xargs -0 -I{} codesign --force --timestamp --options runtime \
      --entitlements "$ENTITLEMENTS" --sign "$IDENTITY" {} 2>/dev/null || true

echo "signing the bundle ..."
codesign --force --timestamp --options runtime \
         --entitlements "$ENTITLEMENTS" --sign "$IDENTITY" "$APP"

echo "verifying signature ..."
codesign --verify --deep --strict --verbose=2 "$APP"

if [ -n "$SKIP_NOTARIZE" ]; then
  echo "SKIP_NOTARIZE set -- stopping before upload to Apple."
  exit 0
fi

# --- 3. notarise -----------------------------------------------------------
if ! xcrun notarytool history --keychain-profile "$PROFILE" >/dev/null 2>&1; then
  cat >&2 <<MSG

Notarisation profile "$PROFILE" is not stored in your keychain.
Store it once (it will prompt for an app-specific password):

  xcrun notarytool store-credentials "$PROFILE" \\
    --apple-id "you@example.com" --team-id "TEAMID"

Or sign without notarising:  SKIP_NOTARIZE=1 ./sign_and_notarize.sh
MSG
  exit 1
fi

ZIP="dist/NXOSC_Reborn.zip"
rm -f "$ZIP"
/usr/bin/ditto -c -k --keepParent "$APP" "$ZIP"
echo "uploading $(du -h "$ZIP" | cut -f1) to Apple for notarisation ..."
xcrun notarytool submit "$ZIP" --keychain-profile "$PROFILE" --wait

echo "stapling the ticket ..."
xcrun stapler staple "$APP"

echo "final check (this is what Gatekeeper will do):"
spctl --assess --type execute --verbose=2 "$APP"
xcrun stapler validate "$APP"
echo
echo "done -- $APP will now open on other Macs."
