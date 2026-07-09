#!/usr/bin/env bash
# Weekly refresh for the free-Apple-ID 7-day signing expiry: build once, then
# install to every reachable device (USB or same Wi-Fi — pairing already done).
#
#   ./reinstall.sh              # default team
#   TEAM=XXXXXXXXXX ./reinstall.sh
#
# Devices must be awake and on this network (or plugged in) to be reachable.
set -euo pipefail
cd "$(dirname "$0")"
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer

TEAM="${TEAM:-YK4NZ9U7TL}"
APP=build/Build/Products/Debug-iphoneos/YTMusic.app

# devicectl identifier|label
DEVICES=(
  "034EFB07-1E60-5107-A97D-BE9686A0CAEA|iPhone 16 Pro"
  "64B0EE2D-917D-56A3-A4F7-F30848A26BBB|iPad Pro 11 (:333)"
)

LIST="$(xcrun devicectl list devices 2>/dev/null || true)"
reachable() { echo "$LIST" | grep "$1" | grep -q "available"; }

# Build against the generic iOS destination: no device needs to be awake for
# the build, and -allowProvisioningUpdates still refreshes the profile for all
# already-registered devices. (Registering a NEW device still needs a one-off
# `./build.sh device <team> <device_id>` with that device unlocked.)
./build.sh device "$TEAM"

ok=0; skipped=""
for d in "${DEVICES[@]}"; do
  id="${d%%|*}"; name="${d##*|}"
  if reachable "$id"; then
    echo "Installing on $name ..."
    if xcrun devicectl device install app --device "$id" "$APP"; then
      ok=$((ok + 1))
    else
      skipped="$skipped, $name (install failed)"
    fi
  else
    skipped="$skipped, $name (unreachable)"
  fi
done

echo
echo "Refreshed $ok device(s) — re-signed for another 7 days."
if [ -n "$skipped" ]; then
  echo "Skipped:${skipped#,}"
  echo "Rerun this script once that device is reachable — the rebuild may have"
  echo "invalidated its current install, so refresh it soon."
fi
