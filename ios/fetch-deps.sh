#!/usr/bin/env bash
# Reproduce the git-ignored heavy bits: the embedded Python framework + vendored deps.
# Run once after cloning, before ./build.sh.
set -euo pipefail
cd "$(dirname "$0")"

PY_SUPPORT_URL="https://github.com/beeware/Python-Apple-support/releases/download/3.13-b14/Python-3.13-iOS-support.b14.tar.gz"

if [ ! -d Support/Python.xcframework ]; then
  echo "Fetching python-apple-support (Python.xcframework)..."
  mkdir -p Support && cd Support
  curl -L -o py-support.tar.gz "$PY_SUPPORT_URL"
  tar xzf py-support.tar.gz Python.xcframework
  rm -f py-support.tar.gz
  cd ..
fi

echo "Vendoring pure-Python deps into app_packages..."
PIP="${PIP:-../.venv/bin/pip}"
[ -x "$PIP" ] || PIP=pip3
# Extraction + JS solver (no deps) and YT-Music search stack (requests/ytmusicapi).
"$PIP" install --target app_packages --no-deps --upgrade yt-dlp yt-dlp-ejs certifi
"$PIP" install --target app_packages --upgrade ytmusicapi requests
# iOS can't load macOS/x86 .so; charset_normalizer etc. have pure-Python fallbacks.
find app_packages -name "*.so" -delete
find app_packages -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf app_packages/bin app_packages/share 2>/dev/null || true

echo "Done. Next: brew install xcodegen (if needed), then ./build.sh sim"
