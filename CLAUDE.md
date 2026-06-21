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

### Windows Named Pipe IPC (mpv Communication)

**Problem:** Python's `FileIO` on a Windows named pipe serializes all read/write access via an internal lock. A blocking `read()` in a reader thread holds the lock, preventing the main thread from writing commands → deadlock.

**Solution:** Single event-loop thread in `_MpvIPC`:
- Uses `PeekNamedPipe` (via ctypes) to non-blocking check bytes available before reading
- Drains outbound command queue before each poll cycle
- Main thread enqueues commands and waits on `threading.Event` for responses

**File:** `player.py:_MpvIPC._loop()` — Do not refactor to async/await or concurrent reader/writer threads without solving the FileIO lock contention.

### mpv IPC: end-file Event Filtering

**Problem:** Every `loadfile replace` command fires `end-file[reason=stop]` for the currently-playing track. If `on_end` callback fires for all end-file events, it advances the queue → another loadfile → another end-file → cascade through entire queue instantly.

**Solution:** In `_dispatch()`, only call `on_end` for `reason in ('eof', 'error')`. Ignore `reason='stop'`.

**File:** `player.py:_MpvIPC._dispatch()` — This filter is critical to prevent audio from skipping through entire playlist instantly.

### mpv Pipe Argument

- Pass short name `ytm-tui` to `--input-ipc-server` (mpv creates the full `\\.\pipe\ytm-tui` path automatically)
- Python connects using full path `open(r'\\.\pipe\ytm-tui', ...)`

### Textual Tab Key

Textual reserves the Tab key for focus cycling. Source-cycle binding uses `t` instead.

### mpv Pre-start in Background

`on_mount()` spawns a background thread to call `_ensure_mpv_running()` early. This avoids the 4.5s startup delay on first play. Race condition prevented by `_start_lock` in `_ensure_mpv_running()`.

## Cross-Platform Notes

**Current:** Windows-only IPC (named pipes + `ctypes.windll` + `msvcrt`).

**Mac/Linux:** Would require refactoring `player.py` to use Unix domain sockets instead of named pipes:
- Replace `\\.\pipe\ytm-tui` with `/tmp/ytm-tui.sock`
- Replace `PeekNamedPipe` with `select()` or `socket.recv(..., MSG_PEEK)`
- Pass `--input-ipc-server=/tmp/ytm-tui.sock` to mpv (mpv supports this on Unix)
- Textual, yt-dlp, mpv all cross-platform; only IPC layer is Windows-specific

**Effort to Mac-compatible:** ~2–3 hours for IPC refactoring. Textual and yt-dlp need no changes.

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
