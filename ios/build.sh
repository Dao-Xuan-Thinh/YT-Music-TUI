#!/usr/bin/env bash
# Build/run helper for the native iOS spike.
#
#   ./build.sh sim         # build, install, launch on an iOS Simulator (auto-creates one)
#   ./build.sh device TEAMID   # build to a connected iPhone (Phase 3; needs Apple ID team)
#
# Requires: Xcode (full), XcodeGen, python-apple-support under Support/Python.xcframework.
set -euo pipefail
cd "$(dirname "$0")"
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer

xcodegen generate >/dev/null
MODE="${1:-sim}"

if [ "$MODE" = "sim" ]; then
  UDID=$(xcrun simctl list devices booted 2>/dev/null | grep -oE '[0-9A-F-]{36}' | head -1 || true)
  if [ -z "${UDID:-}" ]; then
    UDID=$(xcrun simctl create "ytm-test" \
      "com.apple.CoreSimulator.SimDeviceType.iPhone-17" \
      "$(xcrun simctl list runtimes 2>/dev/null | grep -oE 'com.apple.CoreSimulator.SimRuntime.iOS-[0-9-]+' | head -1)")
    xcrun simctl boot "$UDID"
  fi
  echo "Simulator: $UDID"
  xcodebuild -project YTMusic.xcodeproj -scheme YTMusic -configuration Debug \
    -destination "platform=iOS Simulator,id=$UDID" -derivedDataPath build \
    ARCHS=arm64 ONLY_ACTIVE_ARCH=YES build
  xcrun simctl install "$UDID" build/Build/Products/Debug-iphonesimulator/YTMusic.app
  rm -rf build/Build/Intermediates.noindex
  xcrun simctl launch --console-pty "$UDID" com.ytmtui.YTMusic

elif [ "$MODE" = "device" ]; then
  TEAM="${2:?Usage: ./build.sh device <DEVELOPMENT_TEAM_ID> [device_id]}"
  DEVID="${3:-}"
  DEST='generic/platform=iOS'
  [ -n "$DEVID" ] && DEST="platform=iOS,id=$DEVID"
  echo "Building for device with team $TEAM (dest: $DEST) ..."
  # -allowProvisioningUpdates lets xcodebuild create the dev cert + provisioning
  # profile and register the device (required for a free Apple ID).
  xcodebuild -project YTMusic.xcodeproj -scheme YTMusic -configuration Debug \
    -destination "$DEST" -derivedDataPath build -allowProvisioningUpdates \
    DEVELOPMENT_TEAM="$TEAM" CODE_SIGN_STYLE=Automatic \
    ARCHS=arm64 ONLY_ACTIVE_ARCH=YES build
  echo "Built. Install on the connected device with:"
  echo "  xcrun devicectl device install app --device <DEVICE_UDID> build/Build/Products/Debug-iphoneos/YTMusic.app"
else
  echo "Usage: ./build.sh [sim|device <TEAMID>]"; exit 1
fi
