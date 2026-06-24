# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**YouTube Music TUI** — A lightweight terminal UI for streaming audio from YouTube Music and YouTube directly to mpv or ffplay, without downloading files to disk.

**Why lightweight?** The browser-based YouTube Music is heavy even on high-end hardware. This TUI prioritizes speed and minimal resource consumption.

**Run:** `python main.py` from this directory. Requires Python 3.11+, yt-dlp, textual, and mpv (or ffplay as fallback).

## Architecture

The project is modular with clear separation of concerns:

```
main.py         ← Entry point; Textual TUI wiring, home screen, keybindings, playback flow
youtube.py      ← yt-dlp + ytmusicapi wrapper: resolve() (URL or keyword), search(), playlists,
                  auth (cookies/browser + OAuth device flow) + authenticated client, get_home() feed
player.py       ← mpv IPC + ffplay fallback; single-thread event loop for non-blocking IPC
config.py       ← JSON persistence: cookies_file, volume, search_source, theme, app_mode
library.py      ← JSON persistence: liked songs, saved playlists, pinned folders, recent, sessions
offline.py      ← Local audio folder scanner (mutagen tags) for offline mode
updater.py      ← Self-update via git (check/pull/deps refresh, branch switch) + re-exec on restart
```

### Core Flow

1. **Boot** → a `HomeScreen` shows: a Resume-session dropdown, plus Folders /
   Liked / Recent tabs (backed by `library.py`). Selecting loads/plays; Esc or
   "Search / Browse" enters the main UI.
2. **Search** (`/` key) → `youtube.resolve()` detects URL or keyword → results populate DataTable
3. **Play** (Enter on result) → `player.play(url, start=)` loads URL via mpv IPC `loadfile replace`
4. **Queue**: selecting a result makes the whole loaded list the queue and positions the
   index at the chosen track (so jumping matches auto-advance — the `n/total` counter stays
   stable). On track end, auto-advances (honoring `shuffle` and `repeat` off/one/all).
   `add_recent()` records each play.
5. **Settings** (`s`) sets cookies/local-folder (with `~` expansion + ✓/✗); **quit** (`q`)
   confirms when playing and saves a resume session.

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
- Keybindings: `/` search · `f` filter · `space` pause · `n` next · `p` play-next · `a` +queue · `x` stop · `Q` queue/library · `z` shuffle · `r` repeat · `l` like · `w` save playlist · `h` home · `t` source · `o` online/offline · `c`/`C` theme · `+/-` volume · `←→` seek · `s` settings · `g` account/sign-in · `u` update · `?` key list · `q` quit
- The footer is a custom info bar (mode/source/shuffle/repeat/queue/volume/theme); `?` is the only key hint and opens the full `KeybindingsScreen`.

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
| `main.py` | Textual App: home screen, modals, bindings, search/play flow |
| `youtube.py` | yt-dlp + ytmusicapi wrapper: search, URL/playlist resolution, metadata; OAuth login (`login`/`logout`/`configure_auth`/`is_authenticated`) + `ytm_home()` feed |
| `YOUTUBE_LOGIN.md` | User guide: create a Google Cloud OAuth client + sign in (the `g` flow) |
| `oauth.json` | Auto-created OAuth token cache (gitignored) |
| `player.py` | mpv IPC + ffplay fallback; per-OS transport (named pipe / AF_UNIX) |
| `config.py` | JSON settings persistence (cookies, volume, source, theme, app_mode) |
| `library.py` | JSON persistence: liked, playlists, pinned folders, recent, sessions |
| `offline.py` | Local audio folder scanner (mutagen tags) |
| `updater.py` | Self-update: git fetch/compare, ff-only pull, deps refresh, branch switch, re-exec |
| `requirements.txt` | Python dependencies |
| `config.json` | Auto-created runtime config (gitignored) |
| `library.json` / `sessions.json` | Auto-created library + resume sessions (gitignored) |

## Common Tasks

**Search a keyword:** Press `/`, type query, Enter

**Play a URL:** Press `/`, paste YouTube URL, Enter

**Set cookies (for age-restricted content):** Press `s`, enter Netscape format .txt path, Save

**Change volume:** `+` / `-` keys

**Seek:** `←` / `→` (±10 seconds)

**Next track in queue:** `n`

**Switch search source:** `t` (cycles YT Music → YouTube → Both)

**Sign in to YouTube:** `g` opens the Account screen with two methods (config
`auth_method`: `none`/`oauth`/`cookies`). Once authenticated, the home screen's **For
You** tab and search personalize. Setup: `YOUTUBE_LOGIN.md`.
- **Cookies (works):** point it at a `cookies.txt` exported from a logged-in
  music.youtube.com; ytmusicapi uses it as browser auth (SAPISIDHASH), which `youtubei`
  accepts. Reuses the app's `cookies_file`. Built in `youtube._browser_headers_from_cookies`
  / `cookies_auth_ok`.
- **OAuth (device flow):** kept, but **YouTube Music currently rejects OAuth tokens with
  `HTTP 400 INVALID_ARGUMENT`** (Google disabled third-party-client tokens for `youtubei`;
  no client-side fix, 1.12.1 is the latest ytmusicapi). Token in `oauth.json` (gitignored).

`youtube.configure_auth(method, …, cookies_file)` wires the active method at boot;
`youtube._get_ytm()` builds the matching `YTMusic` (cookies → `auth=headers`, oauth →
`oauth_credentials`, else anonymous), degrading to anonymous on error. `auth_status()`
labels the footer.

**Like / save a playlist:** `l` likes the highlighted/playing track; `w` saves the current list as a named playlist (both appear on the home screen)

**Shuffle / repeat:** `z` shuffles the queue; `r` cycles repeat off → one → all

**Resume a session:** pick one from the home screen's Resume dropdown (sessions are saved on quit)

**See all keys:** `?`

**Update the app:** `u` — opens the Update screen (`UpdateScreen`) showing the current
branch + revision, with options to **update this branch** or **switch branches** (e.g.
`master` ↔ `test`). Update fetches the remote; if newer commits exist it confirms,
fast-forward-pulls, reinstalls deps when `requirements.txt` changed, then offers to
restart (re-execs the interpreter). Switching checks out the chosen branch (creating a
local tracking branch from `origin/<branch>` if needed), ff-pulls, refreshes deps, and
offers to restart. A background check at boot flags an available update in the footer
(`↑ update (u)`). Requires the install to be a git checkout with an upstream remote;
otherwise `u` reports "update with git pull". Refuses to run if the working tree has
local changes (stash/commit first). Branch backend lives in `updater.py`
(`current_branch`, `list_branches`, `switch_branch`).
