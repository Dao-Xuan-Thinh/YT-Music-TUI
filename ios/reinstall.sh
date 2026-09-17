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

# <UDID>|<devicectl identifier>|<label>
#
# devicectl has listed these under BOTH forms at different times — the CoreDevice
# identifiers changed when the Xcode account was removed and re-added, and every
# device then read as "unreachable" because the script only knew the old ids. The
# UDID is the stable one (it is also what the provisioning profiles carry), so
# match on either and install with whichever devicectl currently knows.
DEVICES=(
  "00008140-000C109421DB801C|034EFB07-1E60-5107-A97D-BE9686A0CAEA|iPhone 16 Pro"
  "00008142-0004118C0E22401C|64B0EE2D-917D-56A3-A4F7-F30848A26BBB|iPad Pro 11 (:333)"
)
# Installed directly rather than waiting for the phone to hand the app over —
# that path stays silent when anything is off. (The watch must be registered with
# the team first; see the watchOS notes in CLAUDE.md.)
WATCH_DEVICES=(
  "00008310-000C4BE60180E01E|6CBD754F-EE48-54C0-8F10-4954FEE57931|Apple Watch SE 3"
)

LIST="$(xcrun devicectl list devices 2>/dev/null || true)"

# devicectl's State column has several healthy values — "available (paired)"
# when it's reachable over the network, "connected" while a tunnel is actually
# up (which is what you get right after Xcode has talked to the device). Only
# "unavailable" means we can't install. Matching on the substring "available"
# alone got this backwards twice over: it rejected connected devices AND
# accepted unavailable ones. Compare the state that follows the identifier, and
# rule out "unavailable" first so the substring can't fool us.
# Echo the id devicectl currently lists this device under (UDID or CoreDevice id),
# and only when its state is healthy. Empty output = not reachable.
resolve_device() {
  local id line state
  for id in "$@"; do
    [ -n "$id" ] || continue
    line="$(echo "$LIST" | grep -F "$id")" || continue
    state="${line#*"$id"}"
    case "$state" in
      *unavailable*)           continue ;;
      *available*|*connected*) echo "$id"; return 0 ;;
    esac
  done
  return 1
}

# Build against the generic iOS destination: no device needs to be awake for
# the build, and -allowProvisioningUpdates still refreshes the profile for all
# already-registered devices.
#
# ── Preflight ────────────────────────────────────────────────────────────────
# Each of these otherwise surfaces only at the END of a ~3 minute build, which is
# what turned a weekly re-sign into a ten-step chore: build, fail, fix, build,
# fail, fix. Checked up front, in about a second.

# Profiles minted for the APP itself (exact match — not .Widget/.watchkitapp),
# newest first.
app_profiles() {
  local dir="$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles"
  [ -d "$dir" ] || return 0
  local p
  for p in "$dir"/*.mobileprovision; do
    [ -e "$p" ] || continue
    if security cms -D -i "$p" 2>/dev/null | plutil -p - 2>/dev/null \
         | grep -q "\"application-identifier\" => \"$TEAM.com.ytmtui.YTMusic\""; then
      echo "$p"
    fi
  done
}

preflight() {
  local prof exp left groups

  # 1. Xcode's Apple ID. A free account loses this session regularly, and without
  #    it every target fails to SIGN — i.e. after the whole build has compiled.
  # Signed in, the list holds one entry per account; signed out it is literally
  # "( )". The entry is a UUID, NOT an email — grepping for '@' reported a
  # perfectly good account as missing.
  if ! defaults read com.apple.dt.Xcode DVTDeveloperAccountManagerAppleIDLists \
       2>/dev/null | grep -q 'identifier'; then
    echo "✗ Xcode has no Apple ID signed in — signing would fail at the end of the build."
    echo
    echo "   Fix (about a minute):"
    echo "     1. Xcode → Settings → Accounts"
    echo "     2. + → Apple ID → sign in"
    echo "     3. rerun this"
    echo
    echo "   Opening Xcode for you…"
    open -a Xcode 2>/dev/null || true
    return 1
  fi

  prof="$(app_profiles | head -1)"
  if [ -n "$prof" ]; then
    # 2. How long the CURRENT signing lasts — you may not need to run at all.
    exp="$(security cms -D -i "$prof" 2>/dev/null \
           | plutil -extract ExpirationDate raw - 2>/dev/null)"
    if [ -n "$exp" ]; then
      left=$(( ( $(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$exp" +%s 2>/dev/null || echo 0) \
                 - $(date +%s) ) / 86400 ))
      [ "$left" -ge 0 ] && echo "· current signing has ~${left} day(s) left (${exp%%T*})"
    fi

    # 3. App Groups on the app's App ID. It drops off whenever the profiles are
    #    re-minted, and then signing fails on an entitlements mismatch — the one
    #    failure that needs Xcode's UI, so it is worth saying before the build.
    groups="$(security cms -D -i "$prof" 2>/dev/null | plutil -p - 2>/dev/null \
              | grep -c 'application-groups' || true)"
    if [ "${groups:-0}" -eq 0 ]; then
      echo "! The app's profile carries no App Group — signing will likely fail."
      echo "  If it does: Xcode → YTMusic target → Signing & Capabilities →"
      echo "  App Groups → tick group.com.ytmtui.YTMusic, then rerun."
    fi
  fi
  return 0
}

preflight || exit 1
echo

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
  if grep -q "application-groups" "$BUILD_LOG"; then
    # Needs Xcode's UI: -allowProvisioningUpdates can create App IDs and register
    # devices, but it cannot re-add an App Group on a free team.
    echo
    echo "✗ Signing failed: the app's App ID lost its App Group."
    echo "    1. Xcode → open ios/YTMusic.xcodeproj"
    echo "    2. YTMusic target → Signing & Capabilities"
    echo "    3. App Groups → tick group.com.ytmtui.YTMusic"
    echo "       (missing section? + Capability → App Groups → + → that exact name)"
    echo "    4. wait for the signing error to clear, quit Xcode, rerun this"
    open -a Xcode 2>/dev/null || true
    exit 1
  elif grep -q "no devices from which to generate" "$BUILD_LOG"; then
    echo
    echo "Team device list is empty — registering each reachable device."
    echo "(they must be unlocked; this takes one build apiece)"
    registered=0
    for d in "${DEVICES[@]}"; do
      udid="${d%%|*}"; name="${d##*|}"; alt="${d#*|}"; alt="${alt%%|*}"
      if resolve_device "$udid" "$alt" >/dev/null; then
        echo
        echo "→ registering $name ..."
        # Register by UDID — that is what the provisioning profile carries.
        if ./build.sh device "$TEAM" "$udid"; then
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

# One build aimed at a specific device, which is what actually registers it with
# the team. The destination platform follows the app being installed: a watchOS
# app must be built for watchOS or its profile never gains the watch.
register_device() {   # udid, app bundle
  local udid="$1" app="$2"
  if [[ "$app" == *"-watchos"* ]]; then
    xcodebuild -project YTMusic.xcodeproj -scheme YTMusicWatch -configuration Debug \
      -destination "platform=watchOS,id=$udid" -derivedDataPath build \
      -allowProvisioningUpdates -allowProvisioningDeviceRegistration \
      DEVELOPMENT_TEAM="$TEAM" CODE_SIGN_STYLE=Automatic build >/dev/null 2>&1
  else
    ./build.sh device "$TEAM" "$udid" >/dev/null 2>&1
  fi
}

install_to() {   # udid, alt id, label, app bundle
  local udid="$1" alt="$2" name="$3" app="$4" id
  if [ ! -d "$app" ]; then
    skipped="$skipped, $name (nothing built at $app)"
    return
  fi
  id="$(resolve_device "$udid" "$alt")" || {
    skipped="$skipped, $name (unreachable)"
    return
  }
  echo "Installing on $name ..."
  local out
  if out="$(xcrun devicectl device install app --device "$id" "$app" 2>&1)"; then
    ok=$((ok + 1))
    echo "$out" | grep -E "App installed|bundleID" || true
  else
    # devicectl buries the actual reason a few lines into a nested error, and
    # "install failed" on its own sends you hunting. The two that actually happen:
    # a locked device (the developer disk image can't mount) and a sleeping one.
    case "$out" in
      *"still locked"*|*"currently locked"*|*"disk image could not be mounted"*)
        skipped="$skipped, $name (LOCKED — unlock it and rerun)" ;;
      *"could not be established"*|*"Timed out"*|*"unreachable"*)
        skipped="$skipped, $name (asleep or off this network — wake it and rerun)" ;;
      *"cannot be installed on this device"*|*"ApplicationVerificationFailed"*)
        # The profile predates this device — it is not in ProvisionedDevices.
        # Registering needs one build aimed at the device itself; for the watch
        # that means a watchOS destination, which the generic build never covers.
        echo "  ! $name is not in the profile — registering it, then retrying"
        if register_device "$udid" "$app"; then
          if out="$(xcrun devicectl device install app --device "$id" "$app" 2>&1)"; then
            ok=$((ok + 1))
            echo "$out" | grep -E "App installed|bundleID" || true
            return
          fi
        fi
        skipped="$skipped, $name (could not be registered — unlock it and rerun)" ;;
      *)
        skipped="$skipped, $name (install failed)" ;;
    esac
    echo "$out" | tail -3
  fi
}

split_entry() {   # <udid>|<alt>|<label> → sets UDID / ALT / LABEL
  UDID="${1%%|*}"; LABEL="${1##*|}"; ALT="${1#*|}"; ALT="${ALT%%|*}"
}
for d in "${DEVICES[@]}"; do
  split_entry "$d"; install_to "$UDID" "$ALT" "$LABEL" "$APP"
done
for d in "${WATCH_DEVICES[@]}"; do
  split_entry "$d"; install_to "$UDID" "$ALT" "$LABEL" "$WATCH_APP"
done

echo
echo "Refreshed $ok device(s) — re-signed for another 7 days."
if [ -n "$skipped" ]; then
  echo "Skipped:${skipped#,}"
  echo "Rerun this script once that device is reachable — the rebuild may have"
  echo "invalidated its current install, so refresh it soon."
fi
