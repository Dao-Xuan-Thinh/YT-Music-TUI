#!/usr/bin/env bash
# Convenience launcher for macOS / Linux.
# First run: creates a .venv (with a modern Python) and installs dependencies.
# Every run: launches the app.   Usage:  ./run.sh
set -e
cd "$(dirname "$0")"

# Put Homebrew on PATH if present so mpv/ffmpeg are found (Apple Silicon + Intel).
[ -d /opt/homebrew/bin ] && PATH="/opt/homebrew/bin:$PATH"
[ -d /usr/local/bin ]    && PATH="/usr/local/bin:$PATH"
export PATH

# Pick the newest Python >= 3.10. macOS ships system python3 = 3.9, which caps
# yt-dlp at an old version that YouTube now rejects (no audio / HTTP 403).
pick_python() {
    if [ -n "$PYTHON" ]; then echo "$PYTHON"; return; fi
    for p in python3.13 python3.12 python3.11 python3.10; do
        command -v "$p" >/dev/null 2>&1 && { echo "$p"; return; }
    done
    command -v python3 >/dev/null 2>&1 && echo python3 || echo ""
}
PY="$(pick_python)"
if [ -z "$PY" ]; then
    echo "ERROR: no python3 found. Install Python 3.10+ (macOS: brew install python@3.12)."
    exit 1
fi
PYVER="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
PYNUM="$("$PY" -c 'import sys;print(sys.version_info[0]*100+sys.version_info[1])')"

if [ "$PYNUM" -lt 310 ]; then
    echo "WARNING: $PY is $PYVER — yt-dlp needs Python 3.10+ to stream YouTube reliably."
    echo "  macOS: brew install python@3.12 ; then 'rm -rf .venv' and re-run ./run.sh"
fi

# Warn if no audio backend is installed.
if ! command -v mpv >/dev/null 2>&1 && ! command -v ffplay >/dev/null 2>&1; then
    echo "WARNING: no 'mpv' or 'ffplay' on PATH. Install an audio backend:"
    echo "  macOS: brew install mpv   |   Debian: sudo apt install mpv ffmpeg   |   Arch: sudo pacman -S mpv ffmpeg"
    echo
fi

# (Re)create the virtualenv + install deps on first run, or if the existing
# venv uses an outdated Python.
if [ -d .venv ]; then
    VENVNUM="$(.venv/bin/python -c 'import sys;print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null || echo 0)"
    if [ "$VENVNUM" -lt 310 ] && [ "$PYNUM" -ge 310 ]; then
        echo "Existing .venv uses an old Python ($VENVNUM); rebuilding with $PY ($PYVER)..."
        rm -rf .venv
    fi
fi
if [ ! -d .venv ]; then
    echo "First run: creating virtualenv ($PY / $PYVER) and installing dependencies..."
    "$PY" -m venv .venv
    .venv/bin/pip install --upgrade pip >/dev/null
    .venv/bin/pip install -r requirements.txt
fi

exec .venv/bin/python main.py "$@"
