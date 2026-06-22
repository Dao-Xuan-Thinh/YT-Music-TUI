# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**YouTube Music TUI** — A lightweight terminal UI for streaming audio from YouTube Music and YouTube directly to mpv or ffplay, without downloading files to disk.

**Why lightweight?** The browser-based YouTube Music is heavy even on high-end hardware. This TUI prioritizes speed and minimal resource consumption.

**Run:** `python main.py` from this directory. Requires Python 3.11+, yt-dlp, textual, and mpv (or ffplay as fallback).

## Architecture

The project is modular with clear separation of concerns:

```
main.py         ← Entry point; Textual TUI wiring, keyboard bindings, playback flow
youtube.py      ← yt-dlp wrapper: resolve() (URL or keyword), search(), get_info()
player.py       ← mpv IPC + ffplay fallback; single-thread event loop for non-blocking IPC
config.py       ← JSON persistence: cookies_file, volume, search_source
```

### Core Flow

1. **Search** (`/` key) → `youtube.resolve()` detects URL or keyword → results populate DataTable
2. **Play** (Enter on result) → `player.play(url)` loads URL via mpv IPC `loadfile replace`
3. **Queue**: selecting a result sets the queue to remaining results; on track end, auto-advances
4. **Settings** (`s` key) → modal to set cookies file path; persisted to config.json

### Key Design Patterns

**Async within threads, not async/await:**
- Search and playback run in daemon threads to avoid blocking Textual event loop
- Results marshaled back via `call_from_thread()` (Textual's thread-to-event-loop bridge)
- Player position/duration polled every 1s via `set_interval()`

**mpv as persistent daemon:**
- `--idle=yes` mode keeps mpv running between tracks; URLs loaded via IPC `loadfile replace`
- IPC avoids blocking on yt-dlp extraction; mpv handles streaming directly
- Position/duration via `observe_property` subscription (mpv pushes updates) instead of polling

## Development

### Dependencies

Install with: `pip install -r requirements.txt`

- **yt-dlp** — YouTube metadata + audio stream extraction
- **textual** — Terminal UI framework (reactive widgets, keyboard input)
- **System:** mpv (preferred) or ffmpeg (fallback; provides ffplay)

### Testing Each Module

**youtube.py:** `python youtube.py "search query"` or `python youtube.py <yt_url>`
- Detects keyword vs URL automatically
- Prints results as JSON

**player.py:** `python player.py`
- Plays test URL for ~20 seconds
- Prints position/duration every 2s
- Tests pause, resume, seek, quit

**config.py:** `python config.py`
- Creates/loads config.json
- Prints current settings

**main.py (full TUI):** `python main.py`
- Keybindings: `/` (search), `space` (pause), `n` (next), `t` (cycle source), `+/-` (volume), `←→` (seek), `s` (settings), `q` (quit)

## Critical Gotchas

### mpv IPC Transport (cross-platform)

`_MpvIPC` runs a **single event-loop thread** that owns all I/O, talking to mpv
over a platform-specific transport (`player.py`):
- **Windows** (`_WinPipeTransport`): named pipe `\\.\pipe\<name>`. Python's `FileIO`
  on a pipe serializes read/write on an internal lock, so a blocking reader thread
  would deadlock writes. Avoided via `PeekNamedPipe` (ctypes) — non-blocking check
  for available bytes before each read.
- **macOS/Linux** (`_UnixSocketTransport`): `AF_UNIX` socket `/tmp/<name>.sock`,
  using `select()` + `recv()` with line buffering.

Both expose `connect / write / poll_line / close`; the loop drains the outbound
command queue, then calls `transport.poll_line()` (non-blocking) and dispatches
JSON. Main thread enqueues commands and waits on `threading.Event` for responses.

**File:** `player.py:_MpvIPC._loop()` — Do not refactor to async/await or concurrent
reader/writer threads; the single-thread + non-blocking-poll model is what avoids
the Windows FileIO lock contention.

### mpv IPC: end-file Event Filtering

**Problem:** Every `loadfile replace` command fires `end-file[reason=stop]` for the currently-playing track. If `on_end` callback fires for all end-file events, it advances the queue → another loadfile → another end-file → cascade through entire queue instantly.

**Solution:** In `_dispatch()`, only call `on_end` for `reason in ('eof', 'error')`. Ignore `reason='stop'`.

**File:** `player.py:_MpvIPC._dispatch()` — This filter is critical to prevent audio from skipping through entire playlist instantly.

### mpv IPC endpoint argument

`--input-ipc-server={_IPC_ARG}` where `_IPC_ARG` is per-process and per-OS (`player.py`):
- **Windows:** short name `ytm-tui-<pid>` → mpv creates `\\.\pipe\ytm-tui-<pid>`; Python connects via that full pipe path.
- **Unix:** a filesystem path `/tmp/ytm-tui-<pid>.sock` → mpv creates the AF_UNIX socket; Python `connect()`s to that path.

The `<pid>` suffix makes the endpoint unique per run so a new launch never connects to a stale `--idle` daemon (that bug caused silent no-audio).

### mpv must find yt-dlp (venv gotcha)

mpv runs as a separate process and resolves `yt-dlp` from its own PATH. In a virtualenv, yt-dlp is next to the venv Python and NOT on the system PATH, so YouTube won't stream. `_find_ytdlp()` locates it (next to `sys.executable`, else PATH) and passes `--script-opts=ytdl_hook-ytdl_path=<path>` to mpv.

### Track URLs use www.youtube.com

`_ytm_track_to_dict()` builds `https://www.youtube.com/watch?v=<id>` (not `music.youtube.com`). Same videoId/audio, but mpv's ytdl_hook fails to load `music.youtube.com/watch` URLs on Linux; the www form works on every OS.

### Textual Tab Key

Textual reserves the Tab key for focus cycling. Source-cycle binding uses `t` instead.

### mpv Pre-start in Background

`on_mount()` spawns a background thread to call `_ensure_mpv_running()` early. This avoids the 4.5s startup delay on first play. Race condition prevented by `_start_lock` in `_ensure_mpv_running()`.

## Cross-Platform Notes

**Status:** runs on Windows, macOS, and Linux. The IPC layer auto-selects a
transport in `player.py` (`_WinPipeTransport` named pipe / `_UnixSocketTransport`
AF_UNIX socket) behind `_IS_WINDOWS`. Verified end-to-end on Windows and on Linux
(via WSL2 + WSLg audio). macOS uses the identical AF_UNIX path (the `/tmp` socket
location avoids the macOS AF_UNIX path-length limit).

**Install mpv per OS:**
- macOS: `brew install mpv`
- Debian/Ubuntu: `sudo apt install mpv ffmpeg`
- Arch: `sudo pacman -S mpv`
- Windows: `scoop install mpv` (or from mpv.io)

Then `pip install -r requirements.txt`. If running in a virtualenv, ensure mpv
can stream YouTube — `_find_ytdlp()` handles this by pointing mpv at the venv's
yt-dlp automatically.

**macOS Python gotcha:** the system `python3` is 3.9, and current yt-dlp (the one
that actually works with today's YouTube) requires **Python 3.10+**. On 3.9, pip
caps yt-dlp at an old release that fails with HTTP 403 / "format not available"
(plays nothing). Use a newer Python: `brew install python@3.12` and build the
venv with it. `run.sh` does this automatically — it prefers `python3.13/3.12/3.11/3.10`
over the bare `python3`, and rebuilds an existing venv that's on an old Python.

## File Guide

| File | Purpose |
|------|---------|
| `main.py` | Textual App: screens, bindings, search/play flow |
| `youtube.py` | yt-dlp wrapper: search, URL resolution, metadata |
| `player.py` | mpv IPC + ffplay fallback; Windows named pipe event loop |
| `config.py` | JSON settings persistence |
| `requirements.txt` | Python dependencies |
| `config.json` | Auto-created runtime config (cookies path, volume, source) |

## Common Tasks

**Search a keyword:** Press `/`, type query, Enter

**Play a URL:** Press `/`, paste YouTube URL, Enter

**Set cookies (for age-restricted content):** Press `s`, enter Netscape format .txt path, Save

**Change volume:** `+` / `-` keys

**Seek:** `←` / `→` (±10 seconds)

**Next track in queue:** `n`

**Switch search source:** `t` (cycles YT Music → YouTube → Both)

**Quit:** `q`
