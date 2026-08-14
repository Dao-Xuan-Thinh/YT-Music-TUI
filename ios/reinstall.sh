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
# The generic iOS build produces the watch app too (it is embedded in YTMusic.app),
# so the wrist can be refreshed from the same build with no extra compile.
WATCH_APP=build/Build/Products/Debug-watchos/YTMusicWatch.app

# devicectl identifier|label
DEVICES=(
  "034EFB07-1E60-5107-A97D-BE9686A0CAEA|iPhone 16 Pro"
  "64B0EE2D-917D-56A3-A4F7-F30848A26BBB|iPad Pro 11 (:333)"
)
# Installed directly rather than waiting for the phone to hand the app over —
# that path stays silent when anything is off. (The watch must be registered with
# the team first; see the watchOS notes in CLAUDE.md.)
WATCH_DEVICES=(
  "6CBD754F-EE48-54C0-8F10-4954FEE57931|Apple Watch SE 3"
)

LIST="$(xcrun devicectl list devices 2>/dev/null || true)"

# devicectl's State column has several healthy values — "available (paired)"
# when it's reachable over the network, "connected" while a tunnel is actually
# up (which is what you get right after Xcode has talked to the device). Only
# "unavailable" means we can't install. Matching on the substring "available"
# alone got this backwards twice over: it rejected connected devices AND
# accepted unavailable ones. Compare the state that follows the identifier, and
# rule out "unavailable" first so the substring can't fool us.
reachable() {
  local line state
  line="$(echo "$LIST" | grep -F "$1")" || return 1
  state="${line#*"$1"}"
  case "$state" in
    *unavailable*)             return 1 ;;
    *available*|*connected*)   return 0 ;;
    *)                         return 1 ;;
  esac
}

# Build against the generic iOS destination: no device needs to be awake for
# the build, and -allowProvisioningUpdates still refreshes the profile for all
# already-registered devices.
#
# A generic build can only refresh profiles for devices the TEAM already knows.
# Removing and re-adding the Xcode account empties that list, and then every
# target fails with "Your team has no devices from which to generate a
# provisioning profile". The cure is one build per device with an explicit
# destination (that's what registers it), so do exactly that, then rebuild
# generic so the final profile carries all of them. Each device must be
# UNLOCKED and reachable for its registration build.
BUILD_LOG="$(mktemp -t ytm-build)"
trap 'rm -f "$BUILD_LOG"' EXIT

if ! ./build.sh device "$TEAM" 2>&1 | tee "$BUILD_LOG"; then
  if grep -q "no devices from which to generate" "$BUILD_LOG"; then
    echo
    echo "Team device list is empty — registering each reachable device."
    echo "(they must be unlocked; this takes one build apiece)"
    registered=0
    for d in "${DEVICES[@]}"; do
      id="${d%%|*}"; name="${d##*|}"
      if reachable "$id"; then
        echo
        echo "→ registering $name ..."
        if ./build.sh device "$TEAM" "$id"; then
          registered=$((registered + 1))
        else
          echo "  ! $name could not be registered (locked?)"
        fi
      else
        echo "→ skipping $name (unreachable)"
      fi
    done
    [ "$registered" -gt 0 ] || {
      echo
      echo "No device could be registered. Unlock one, keep it on this network,"
      echo "and run this again."
      exit 1
    }
    echo
    echo "→ rebuilding with all registered devices in the profile ..."
    ./build.sh device "$TEAM"
  else
    exit 1
  fi
fi

ok=0; skipped=""

install_to() {   # id, label, app bundle
  local id="$1" name="$2" app="$3"
  if [ ! -d "$app" ]; then
    skipped="$skipped, $name (nothing built at $app)"
    return
  fi
  if ! reachable "$id"; then
    skipped="$skipped, $name (unreachable)"
    return
  fi
  echo "Installing on $name ..."
  if xcrun devicectl device install app --device "$id" "$app"; then
    ok=$((ok + 1))
  else
    skipped="$skipped, $name (install failed)"
  fi
}

for d in "${DEVICES[@]}"; do
  install_to "${d%%|*}" "${d##*|}" "$APP"
done
for d in "${WATCH_DEVICES[@]}"; do
  install_to "${d%%|*}" "${d##*|}" "$WATCH_APP"
done

echo
echo "Refreshed $ok device(s) — re-signed for another 7 days."
if [ -n "$skipped" ]; then
  echo "Skipped:${skipped#,}"
  echo "Rerun this script once that device is reachable — the rebuild may have"
  echo "invalidated its current install, so refresh it soon."
fi
