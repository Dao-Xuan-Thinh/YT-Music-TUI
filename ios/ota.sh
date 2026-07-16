#!/usr/bin/env bash
# OTA-install the current build over Tailscale — for when the devices are NOT
# on the home Wi-Fi. devicectl needs same-LAN mDNS + Apple's trust tunnel, but
# Apple's itms-services OTA install only needs an HTTPS URL with a valid cert,
# which `tailscale serve` provides (*.ts.net / Let's Encrypt).
#
# ⚠ REQUIRES A PAID Apple Developer membership. Free personal-team profiles
# are marked LocalProvision=true and iOS only accepts them via the direct
# developer-tools channel (Xcode/devicectl) — itms-services shows the install
# progress bar, then silently rolls back to the previous version. Verified
# 2026-07-16 (perfect archive+development-export ipa, correct manifest, both
# attempts rolled back; the profile flag is the blocker). With a paid team
# (ad-hoc or development profile) this script works as-is.
#
#   ./ota.sh                archive + development-export an OTA ipa and serve
#                           it on the tailnet (port 8445, tailnet-only)
#   ./ota.sh stop           stop serving
#   ./ota.sh serve <TEAM>   override the signing team (default YK4NZ9U7TL)
#
# On the device: Tailscale ON → open the printed URL in Safari → tap install.
# Works because the dev provisioning profile inside the app already contains
# the device UDIDs; installs as a normal update over the existing app.
set -euo pipefail
cd "$(dirname "$0")"

PORT=8445        # tailnet-facing HTTPS port
LOCAL_PORT=8099  # localhost static server tailscale proxies to (macOS's
                 # sandboxed Tailscale can't serve filesystem paths directly)
APP=build/Build/Products/Debug-iphoneos/YTMusic.app
OTA=build/ota
PIDFILE=$OTA/server.pid

if [ "${1:-}" = "stop" ]; then
  tailscale serve --https=$PORT off 2>/dev/null || true
  [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null || true
  rm -f "$PIDFILE"
  echo "OTA serving stopped."
  exit 0
fi

[ -e YTMusic.xcodeproj/project.pbxproj ] || { echo "No YTMusic.xcodeproj — run ./build.sh once first (xcodegen + BuildInfo)."; exit 1; }

TEAM="${2:-${TEAM:-YK4NZ9U7TL}}"
HOST=$(tailscale status --json | python3 -c "import json,sys; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))")
BASE="https://$HOST:$PORT"

# A raw Debug-iphoneos .app zipped by hand installs via devicectl but gets
# ROLLED BACK by installd on the OTA path (debug/preview stub dylibs + debug
# signing). archive + development-export produces the canonical OTA ipa —
# and writes the manifest.plist for us.
echo "Archiving YTMusic (development export — takes a few minutes)…"
rm -rf "$OTA" && mkdir -p "$OTA"
cat > "$OTA/export-options.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key><string>development</string>
  <key>teamID</key><string>$TEAM</string>
  <key>compileBitcode</key><false/>
  <key>thinning</key><string>&lt;none&gt;</string>
  <key>manifest</key>
  <dict>
    <key>appURL</key><string>$BASE/YTMusic.ipa</string>
    <key>displayImageURL</key><string>$BASE/icon.png</string>
    <key>fullSizeImageURL</key><string>$BASE/icon.png</string>
  </dict>
</dict>
</plist>
EOF
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild archive \
    -project YTMusic.xcodeproj -scheme YTMusic \
    -destination "generic/platform=iOS" \
    -archivePath "$OTA/YTMusic.xcarchive" \
    -derivedDataPath build \
    ARCHS=arm64 ONLY_ACTIVE_ARCH=YES \
    CODE_SIGN_STYLE=Automatic DEVELOPMENT_TEAM="$TEAM" \
    -allowProvisioningUpdates -quiet
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild -exportArchive \
    -archivePath "$OTA/YTMusic.xcarchive" \
    -exportPath "$OTA" \
    -exportOptionsPlist "$OTA/export-options.plist" \
    -allowProvisioningUpdates -quiet

ARCHIVED_APP="$OTA/YTMusic.xcarchive/Products/Applications/YTMusic.app"
VER=$(defaults read "$PWD/$ARCHIVED_APP/Info" CFBundleShortVersionString)
# Manifest display icon (required keys) — reuse the app icon.
cp "$ARCHIVED_APP/AppIcon60x60@2x.png" "$OTA/icon.png" 2>/dev/null \
    || cp "$ARCHIVED_APP"/AppIcon*.png "$OTA/icon.png" 2>/dev/null || true

cat > "$OTA/index.html" <<EOF
<!doctype html>
<meta name="viewport" content="width=device-width, initial-scale=1">
<body style="background:#0b0f0c;color:#e8f0e8;font-family:ui-monospace,monospace;
             display:flex;align-items:center;justify-content:center;height:90vh">
<div style="text-align:center">
  <div style="font-size:42px">&#9834;</div>
  <p>YTMusic $VER</p>
  <p><a style="color:#4dd97a;font-size:20px"
        href="itms-services://?action=download-manifest&amp;url=$BASE/manifest.plist">
     tap to install</a></p>
  <p style="color:#8a998a;font-size:12px">then check the home screen for the install progress</p>
</div>
EOF

# Localhost-only static server; tailscale terminates TLS and proxies to it.
[ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null || true
(python3 -m http.server "$LOCAL_PORT" --bind 127.0.0.1 --directory "$PWD/$OTA" \
    >/dev/null 2>&1 & echo $! > "$PIDFILE")
tailscale serve --https=$PORT off 2>/dev/null || true
tailscale serve --bg --https=$PORT "http://127.0.0.1:$LOCAL_PORT" >/dev/null
echo
echo "Serving (tailnet only): open on the device with Tailscale ON:"
echo "  $BASE"
echo
echo "Stop with: ./ota.sh stop"
