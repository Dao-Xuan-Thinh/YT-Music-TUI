#!/usr/bin/env bash
# Convenience launcher for macOS / Linux.
# First run: creates a .venv and installs dependencies. Every run: launches the app.
#   ./run.sh
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

# Warn (don't fail) if no audio backend is installed.
if ! command -v mpv >/dev/null 2>&1 && ! command -v ffplay >/dev/null 2>&1; then
    echo "WARNING: neither 'mpv' nor 'ffplay' found on PATH. Install an audio backend:"
    echo "  Debian/Ubuntu : sudo apt install mpv ffmpeg"
    echo "  Arch          : sudo pacman -S mpv ffmpeg"
    echo "  macOS         : brew install mpv ffmpeg"
    echo
fi

# Create the virtualenv + install deps on first run.
if [ ! -d .venv ]; then
    echo "First run: creating virtualenv and installing dependencies..."
    "$PY" -m venv .venv
    .venv/bin/pip install --upgrade pip >/dev/null
    .venv/bin/pip install -r requirements.txt
fi

exec .venv/bin/python main.py
