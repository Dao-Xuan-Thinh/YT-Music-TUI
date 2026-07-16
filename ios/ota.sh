#!/usr/bin/env bash
# OTA-install the current device build over Tailscale — for when the devices are
# NOT on the home Wi-Fi. devicectl needs same-LAN mDNS + Apple's trust tunnel,
# but Apple's itms-services OTA install only needs an HTTPS URL with a valid
# cert, which `tailscale serve` provides (*.ts.net / Let's Encrypt).
#
#   ./ota.sh          package build/Build/Products/Debug-iphoneos/YTMusic.app
#                     and serve it on the tailnet (port 8445, tailnet-only)
#   ./ota.sh stop     stop serving
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

[ -d "$APP" ] || { echo "No device build at $APP — run ./build.sh device <team> (or ./reinstall.sh) first."; exit 1; }

HOST=$(tailscale status --json | python3 -c "import json,sys; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))")
VER=$(defaults read "$PWD/$APP/Info" CFBundleShortVersionString)
BASE="https://$HOST:$PORT"

echo "Packaging YTMusic $VER for OTA…"
rm -rf "$OTA" && mkdir -p "$OTA/work/Payload"
cp -R "$APP" "$OTA/work/Payload/"
(cd "$OTA/work" && zip -qry ../YTMusic.ipa Payload)
rm -rf "$OTA/work"

cat > "$OTA/manifest.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>items</key>
  <array>
    <dict>
      <key>assets</key>
      <array>
        <dict>
          <key>kind</key><string>software-package</string>
          <key>url</key><string>$BASE/YTMusic.ipa</string>
        </dict>
      </array>
      <key>metadata</key>
      <dict>
        <key>bundle-identifier</key><string>com.ytmtui.YTMusic</string>
        <key>bundle-version</key><string>$VER</string>
        <key>kind</key><string>software</string>
        <key>title</key><string>YTMusic</string>
      </dict>
    </dict>
  </array>
</dict>
</plist>
EOF

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
