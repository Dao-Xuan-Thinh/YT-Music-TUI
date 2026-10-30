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
                  auth (cookies/browser) + authenticated client, get_home() feed
player.py       ← mpv IPC + ffplay fallback; single-thread event loop for non-blocking IPC
config.py       ← JSON persistence: cookies_file (streaming) + auth_cookies_file (account),
                  account_name, volume, search_source, theme, app_mode
library.py      ← JSON persistence: liked songs, saved playlists, pinned folders, recent, sessions
offline.py      ← Local audio folder scanner (mutagen tags) for offline mode
updater.py      ← Self-update via git (check/pull/deps refresh, branch switch) + re-exec on restart
```

### Core Flow

1. **Boot** → a `HomeScreen` shows tabs **Resume / For You / Folders / Liked /
   Recent** (backed by `library.py`). `←/→` switch tabs (and auto-focus that tab's
   list so a row is always highlighted). Selecting loads/plays/resumes; on any
   manageable tab `d` deletes the highlighted entry (unlike / unpin / delete
   playlist or session) and `r` renames a highlighted playlist — a one-line
   `#home-status` reports the result (or why nothing happened). Esc or
   "Search / Browse" enters the main UI.
2. **Search** (`/` key) → `youtube.resolve()` detects URL or keyword → results populate DataTable
3. **Play** (Enter on result) → `player.play(url, start=)` loads URL via mpv IPC `loadfile replace`
4. **Queue**: selecting a result makes the whole loaded list the queue and positions the
   index at the chosen track (so jumping matches auto-advance — the `n/total` counter stays
   stable). On track end, auto-advances (honoring `shuffle` and `repeat` off/one/all).
   `add_recent()` records each play.
5. **Settings** (`s`) holds ONLY the listen-stats sync settings (GitHub token +
   device name). Streaming cookies (age-restricted playback, player-only) live in
   Account (`g`) with live ✓/✗ + immediate apply; the offline folder is set by
   typing its path in the search bar while in offline mode (`o`). **Quit** (`q`)
   asks when playing: *Save & quit* (y) saves a resume session, *Just quit* (n)
   quits without one, Esc stays in the app. The home screen's `q` routes through
   the same `App.action_quit` — a bare `app.exit()` there skipped the stats flush
   and `player.quit()`, leaving the mpv daemon playing.

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

Nothing to install by hand: `main.py` calls `bootstrap.ensure()` **before its
first third-party import**, so a fresh clone on a new machine pip-installs
whatever `requirements.txt` is missing and re-execs itself.

- **yt-dlp** — YouTube metadata + audio stream extraction
- **textual** — Terminal UI framework (reactive widgets, keyboard input)
- **System:** mpv (preferred) or ffmpeg (fallback; provides ffplay) — not a pip
  package, so `bootstrap` prints the command for this OS and offers to run the
  platform package manager (brew / winget / apt / pacman / dnf / zypper).

`bootstrap.py` is stdlib-only (it runs before anything is installed) and:
- parses `requirements.txt` itself, including `sys_platform` markers; a comment
  line starting with `# optional` marks every entry below it as nice-to-have
  (the media-key bindings), so one unbuildable wheel can't stop the app;
- installs into the current interpreter, unless that's a PEP 668
  "externally managed" system Python (Homebrew / Debian / Arch) — then it
  creates (or reuses) the project venv and re-execs into it;
- records a verified install in `.deps-stamp` (keyed on interpreter +
  `requirements.txt` mtime/size) so the ~20 ms metadata check runs only after a
  pull that changes the requirements, not on every launch. A hand-wiped venv is
  still caught by a `find_spec('textual')` probe;
- never loops: the re-exec'd child carries `YTM_BOOTSTRAP_RAN` and reports what
  is still missing instead of installing again.

Escape hatches: `YTM_NO_BOOTSTRAP=1` or `--no-bootstrap`.

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
- Keybindings: `/` search · `f` filter · `space` pause · `n` next · `p` play-next · `a` +queue · `x` stop · `Q` queue/library · `K/J` (or shift+↑/↓) move queue track · `z` shuffle · `r` repeat · `l` like · `w` save playlist · `h` home · `t` source · `o` online/offline · `c`/`C` theme · `+/-` volume · `←→` seek · `s` settings · `g` account/sign-in · `u` update · `?` key list · `q` quit
- The footer is a custom info bar (mode/source/shuffle/repeat/queue/volume/theme); when
  signed in it also shows the account display name (`♥ <name>`) styled in the theme accent
  via a Rich `Text`. `?` is the only key hint and opens the full `KeybindingsScreen`.

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
- **Windows:** short name `ytm-tui-<pid>-<nonce>` → mpv creates `\\.\pipe\<name>`; Python connects via that full pipe path.
- **Unix:** a filesystem path `/tmp/ytm-tui-<pid>-<nonce>.sock` → mpv creates the AF_UNIX socket; Python `connect()`s to that path.

The suffix makes the endpoint unique per run so a new launch never connects to a stale `--idle` daemon (that bug caused silent no-audio). **The pid alone was not unique:** the updater re-execs in place, so the next run has the SAME pid and collided with the daemon the old one left behind — hence `_RUN_NONCE`.

### mpv daemons outlive the app, and publish their own now-playing entry

`--idle=yes` is what keeps mpv between tracks, and nothing in the OS ties a child to its parent: a crash, a `kill -9`, a closed terminal or an in-place re-exec all orphan the daemon, and it keeps running. They pile up — a real case had **66 of them**, the oldest five days old, several from a single run.

`player._sweep_orphans()` runs in a background thread at `Player.__init__`: it lists live mpv, reads the pid back out of each one's `--input-ipc-server` name, and kills only those whose owner is gone (plus our own pid under a different nonce — the re-exec case). A daemon whose owner is still alive belongs to a second running instance and is left alone. It is never a pattern kill: every pid comes out of our own endpoint name. `atexit` also calls `_shutdown_mpv` as a last line of defence.

Each daemon also published **its own entry** to the system now-playing list, named after the socket (`mpv-55554944…`), which both cluttered Control Center and answered the media keys behind the app's back. `--media-controls=no` turns that off — but an mpv too old to know the option **exits** instead of ignoring it, so `_supports_media_controls()` probes once with `mpv --media-controls=no --version` before it's ever passed.

### mpv itself may not be on PATH

`shutil.which('mpv')` is not enough. The Windows mpv installers don't touch PATH
at all (a real case: `C:\Program Files\MPV Player\mpv.exe`), and winget/scoop
only extend the PATH of *new* processes — so a correct install is invisible to
the shell that is already open, and the app used to report "No audio backend"
while mpv sat right there.

`player.find_backend_exe(tool)` checks PATH first, then where installers actually
put things (winget Links/Packages, `Program Files\*mpv*`, scoop shims/apps,
chocolatey bin, `C:\mpv`, `ffmpeg\bin`; Homebrew both prefixes, MacPorts,
`/snap/bin`, `~/.local/bin`, `mpv.app` on Unix). Every spawn uses the resolved
absolute path — `Player.backend_exe`, never the bare name. Only successful
lookups are cached, so installing mpv while the app is open is picked up.

`player.install_hint()` is the single source of the per-OS install command; the
old messages hard-coded `brew install mpv` on every platform. `main.py`'s boot
warning and `bootstrap.py`'s backend check both call it.

### mpv must find yt-dlp (venv gotcha)

mpv runs as a separate process and resolves `yt-dlp` from its own PATH. In a virtualenv, yt-dlp is next to the venv Python and NOT on the system PATH, so YouTube won't stream. `_find_ytdlp()` locates it (next to `sys.executable`, else PATH) and passes `--script-opts=ytdl_hook-ytdl_path=<path>` to mpv.

### Never dismiss a modal from a worker thread (it wedges terminal input)

**The "UI freezes after signing in" bug.** Symptom: after the Account (`g`) cookie
sign-in, the UI kept rendering (header clock ticked, event loop fully alive) but **every
keystroke was ignored**. Cross-platform (Windows / macOS / Linux); a live thread snapshot
showed `textual-input` healthy and parked on the console/TTY handle, just never receiving
events.

**Cause:** the old cookie/OAuth flow validated in a worker thread and dismissed the modal
*from that thread* (`AccountScreen._use_cookies` → `call_from_thread(_after_cookies)` →
`_finish` → `dismiss`). Dismissing a `ModalScreen` from a worker-thread `call_from_thread`
callback wedges Textual's real input driver. It's unique to this flow — every other modal
(Settings, Update, Keybindings) dismisses on the UI thread from a button press and is
fine. It does **not** reproduce under the headless `run_test` driver (no real input
thread), which is why it took live thread/`uidbg.log` snapshots to find. (False leads ruled
out first: not a Python deadlock — a faulthandler watchdog rescheduled each poll tick never
fired; not mpv — `--no-terminal` didn't fix it and it froze with nothing playing.)

**Rule: never dismiss a modal from a worker thread.** Do a fast *local* check on the UI
thread, dismiss there, then do any network validation in the background and update the
footer/status — never dismiss from the thread.

**Fix (current design):** `AccountScreen._use_cookies` runs on the UI thread (button
press): it does only a fast **local** sanity check — file exists +
`youtube._browser_headers_from_cookies(path)` confirms it's a logged-in export (~2 ms) —
then `_finish('cookies', …)` dismisses on the UI thread (proven safe). The live session is
confirmed *after* dismiss by `action_account._after`, which calls `configure_auth` and then
kicks off the existing background `App._verify_account` daemon (the same one boot uses):
it runs `youtube.verify_auth_live()` and marshals the result back via `call_from_thread`
only to set `config.account_name` / `_update_footer()` / alert on a confirmed logout —
never to dismiss a modal. No worker-thread dismiss, no restart.

Related hygiene: mpv is launched with **`--no-terminal`** + **`stdin=DEVNULL`** (ffplay
`-nostdin` + `stdin=DEVNULL`) in `player.py` so a backend can never read terminal keys.
This was *not* the cause of the freeze above (it persisted with `--no-terminal`), but it's
correct — mpv is driven only over the IPC socket and must never touch the terminal.

### Track URLs use www.youtube.com

`_ytm_track_to_dict()` builds `https://www.youtube.com/watch?v=<id>` (not `music.youtube.com`). Same videoId/audio, but mpv's ytdl_hook fails to load `music.youtube.com/watch` URLs on Linux; the www form works on every OS.

### Textual Tab Key

Textual reserves the Tab key for focus cycling. Source-cycle binding uses `t` instead.

### Custom themes + animated color-wave

`CUSTOM_THEMES` (a list of `textual.theme.Theme`) is registered in `on_mount` via
`register_theme()` **before** applying the saved theme, so the custom names appear in the
picker (`c`) and quick-cycle (`C`) next to the built-ins. Because these names aren't in
Textual's `BUILTIN_THEMES`, `config.theme`'s getter no longer validates against that set
(it returns the stored name as-is; the App-level `try/except` around `self.theme = …`
handles a truly-unknown name).

`ANIMATED_PALETTES` maps a subset of theme names → a list of colors. When such a theme is
active **and** a track is actively playing (not paused), a color-wave flows across the
now-playing bar and the playing `▸` row. `_wave_text(s, palette, frame)` colors each char
by an interpolated, frame-advancing position along the (cyclic) palette. `_sync_animation()`
starts/stops a ~12 fps `set_interval` (`_anim_timer`) based on `theme ∈ ANIMATED_PALETTES
and now_playing and not is_paused`; it's called from `_poll_player` (1 Hz) plus the
play/theme-change hooks, so **the timer is fully stopped whenever the wave isn't visible —
zero idle cost** (preserves the lightweight goal). `_animate_tick` updates only the
`#now-playing` Static and the 4 cells of the one playing row (`_playing_row`, recorded in
`_render_table`) via `update_cell_at` — never a full-table rebuild. While the wave runs it
owns `#now-playing`, so `_update_player_bar` skips that widget (avoids a 1 Hz flicker).

### mpv Pre-start in Background

`on_mount()` spawns a background thread to call `_ensure_mpv_running()` early. This avoids the 4.5s startup delay on first play. Race condition prevented by `_start_lock` in `_ensure_mpv_running()`.

### Cover art: one cache, three consumers, and a cell is two pixels

`artwork.py` downloads a track's cover ONCE into `.art-cache/` (keyed on the
URL) and every consumer reads that same file: the side panel's upper section
(the playing track) and lower section (the row under the table cursor) render
it, and `mediakeys.set_now_playing(..., art_path)` hands the path to the OS panel
(macOS `MPMediaItemArtwork`, MPRIS `mpris:artUrl`, SMTC `display_updater
.thumbnail`). So the download is driven by **playback**, not by the panel —
`_play_queue_item` kicks it off whenever a media-keys backend exists, because
Control Center is visible even when the terminal is too narrow for the panel.

- **Three renderers, chosen by `config.art_style`.** Each colors per cell, and
  `fit()` is the only place the aspect math lives — it returns CELLS, and each
  renderer resizes to its own subpixel grid:
  - `braille` (the default): 2x4 dots per cell, so eight times the detail of
    the ramp. The dots are on/off, so shading comes from Floyd-Steinberg
    dithering (`convert('1')`) and color from the cell average. Resizes to
    `cols*2 x rows*4`.
  - `ascii`: one glyph per pixel from `_RAMP`. Resizes to `cols x rows`.
  - `blocks`: `▀` with the top pixel as foreground and the bottom as
    background — two pixels per cell, closer to a photo. Resizes to
    `cols x 2*rows`.
- **The luminance must be stretched first** (`_stretch`, `autocontrast(cutoff=12)`).
  Most covers live in the bottom third of the scale and map to nothing but `.`
  and `:` (or a sparse dot field) — noise, not a picture. Equalizing the
  histogram reads better still on a flat cover but blows a letterboxed one into
  a solid block.
- **Braille needs a font that has U+28xx.** Most programming fonts do
  (JetBrains Mono, Nerd Fonts); one that doesn't shows tofu, and `art_style`
  is the way out.
- **The cursor half is debounced** (`_cursor_since`, 0.3 s): without it, holding
  ↓ fires one download per row passed.
- **The detail lines** (album, release year, play count) come from
  `youtube.ytm_track_details`, which needs TWO ytmusicapi calls because no
  single endpoint carries all of it: `get_watch_playlist` has the album and the
  year (plus, signed in, the account's like / in-library state), `get_song`
  the play count. Your own line under it is LOCAL and instant: plays and
  listened time summed over every stats key that starts with `<video id>|`,
  because desktop and iOS can file the same track under slightly different
  titles. Cached per track id in `App._details`,
  including the empty result — a local file or a dead id must not re-query
  every time it comes up. Daemon thread only (it takes `_ytm_lock`).
- **Measure, don't compute, the panel's inner width** (`#art-image`.size.width).
  Border + padding come from CSS; a cover one cell too wide wraps, and a
  wrapped half-block row shears the whole picture diagonally.
- **The panel never steals width from the table.** It appears only above
  `ART_TABLE_COLS` (the table's own columns add up to 82) and hides itself on
  the way back down, so a normal 80-column terminal is untouched.
- **Pillow is optional** (below the `# optional` marker, like the media-key
  deps). Without it `artwork.available()` is False, the panel never shows, and
  the OS panel still gets its cover — fetching needs no decoder.
- YouTube's per-video image is always 4:3, so a 16:9 frame arrives letterboxed
  and a square cover pillarboxed; `_autocrop` trims a uniform border, and
  ignores a crop that would eat most of the picture (a dark cover isn't a
  border). ytmusicapi hands out 120x120 thumbnails — `url_for` rewrites the
  `=w120-h120` suffix Google honors into `=w544-h544` instead of upscaling mud.

### OS media keys: play and pause are directional, never a toggle

`mediakeys.py` maps the system's transport buttons to app callbacks. Play and
Pause must dispatch `play` / `pause` (handled by `_media_play` / `_media_pause`,
which only resume a paused track / only pause a playing one). They used to both
dispatch `toggle_pause`, and that had a real consequence: **every OS sends an
unsolicited Pause when the audio device goes away** (headphones unplugged,
Bluetooth headset powered off). Received as a toggle, a track the user had
paused on purpose started playing out loud through the built-in speakers.

Only an actual toggle button may flip the state: macOS
`togglePlayPauseCommand`, MPRIS `PlayPause`, and the `space` key. SMTC has no
toggle button — Windows decides between PLAY and PAUSE from the
`playback_status` we publish, which is why `set_now_playing` must keep pushing
it.

### Listen-stats schema is a contract with the iOS app

`stats.py` and the iOS `StatsStore`/`StatsModel` read and write the SAME per-device
gist files, so any schema change must land on both or each client will drop the
other's fields the next time it pushes.

**One shared library file.** The library blob (liked / playlists / sessions +
tombstones) is identical on every device, so it lives in ONE file —
`stats.LIB_FILE` = `ytm-library.json` — not inside each device file. Four
embedded copies were most of the gist and are what pushed it past the 1 MB
inline limit. A device publishes its stats file and the shared library in a
single PATCH, so it can never leave half a state behind. A device file written
by a pre-dedup client still carries `library`; that copy is read and merged
(ours included, since deleting it from our own file would otherwise lose it)
and disappears the next time that client syncs. Only the library is shared —
`days`, `top`, `clock` and the record maps stay per-device, which is what keeps
the merge conflict-free. Alongside `days` and `top` (a 12-month,
300-key-per-month attribution map) sit the all-time records — `artists`, `tracks`,
`albums`, each `key -> {'s','n','f','l'}` (seconds, plays, first listened, last
listened) — plus `clock` (`'<weekday 0=Mon>-<hour>' -> seconds`) for the heatmap.

- **Merging** (`merged_records`, and the same rule in `_merged_day_map`): our OWN
  device's local vs gist copy is de-duplicated field-by-field (max), because both
  describe the same listening; every OTHER device is independent and adds. Callers
  MUST pass `own_device_id` — without it our own gist copy is treated as a peer and
  the totals inflate.
- **Play counts** are credited once per play past `min(30s, half the track)`.
  `_play_queue_item` calls `begin_track()`; without that a repeat-one loop counts
  as a single endless play, since the track never changes between `add()` calls.
- **`_seed_records`** backfills `artists`/`tracks` from `top` exactly once (guarded
  by the `seeded` flag), seconds only — counts and dates can't be recovered. It
  seeds from the LOCAL map so each device contributes its own history and the
  cross-device sum stays correct.
- `albums` only fills for tracks whose yt-dlp metadata carries an album (YouTube
  Music tracks, not plain videos), and only from v1.7 onward.

**The gist API truncates past 1 MB.** `GET /gists/<id>` inlines each file's
`content` only while the WHOLE response fits in 1 MB; the files past that point
come back with `truncated: true`, a body cut off mid-JSON, and a `raw_url` to
fetch instead. With four devices the gist crossed 1 MB and the last file (the
laptop's) was silently dropped by every client, because both readers parse the
inline `content` and swallow the failure — `except Exception: continue` here,
`guard … else { continue }` in `StatsStore.swift`. Both now refetch from
`raw_url` on `truncated` or a parse failure (`StatsStore._file_body` /
`fileBody`), and a file that still can't be read is named in the sync status
instead of vanishing. Any new client must do the same.

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
- Windows: `winget install --id shinchiro.mpv -e` (or `scoop install mpv`, or mpv.io)

Then just start the app (`./run.sh`, `run.cmd` on Windows, or `python main.py`):
`bootstrap.py` installs the Python dependencies on that first launch. If running
in a virtualenv, ensure mpv can stream YouTube — `_find_ytdlp()` handles this by
pointing mpv at the venv's yt-dlp automatically.

`install.sh` / `install.ps1` only add a global `yttui` launcher; both delegate to
`run.sh` / `run.cmd`, so there is one code path that picks the interpreter.

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
| `youtube.py` | yt-dlp + ytmusicapi wrapper: search, URL/playlist resolution, metadata; account auth (`configure_auth`/`is_authenticated`/`verify_auth_live`) + `ytm_home()` feed |
| `YOUTUBE_LOGIN.md` | User guide: sign in via Browser or Cookies (the `g` flow) |
| `player.py` | mpv IPC + ffplay fallback; per-OS transport (named pipe / AF_UNIX) |
| `config.py` | JSON settings persistence (cookies, volume, source, theme, app_mode) |
| `library.py` | JSON persistence: liked, playlists, pinned folders, recent, sessions |
| `offline.py` | Local audio folder scanner (mutagen tags) |
| `bootstrap.py` | First-boot dependency install (stdlib only; runs before main.py's imports) |
| `artwork.py` | Cover art: download + disk cache, half-block terminal render (needs the optional Pillow) |
| `mediakeys.py` | OS media keys + now-playing panel: macOS helper process / MPRIS2 / SMTC |
| `_mediakeys_darwin_helper.py` | macOS-only subprocess owning the Cocoa run loop for MPRemoteCommandCenter |
| `stats.py` | Listen stats: local JSON + per-device gist sync (schema shared with the iOS app) |
| `updater.py` | Self-update: git fetch/compare, ff-only pull, deps refresh, branch switch, re-exec |
| `requirements.txt` | Python dependencies (everything under `# optional` is non-fatal) |
| `run.sh` / `run.cmd` | Launchers: find a modern Python, make the venv, start the app |
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

**Sign in to YouTube:** `g` opens the Account screen (config `auth_method`:
`none`/`browser`/`cookies`). Once authenticated, the home screen's **For You** tab
and search personalize. Setup: `YOUTUBE_LOGIN.md`.
- **Browser (recommended — durable):** pick a browser *profile* in the Account screen; at
  every launch `youtube._browser_headers_live(browser, profile)` reads the **live**
  music.youtube.com session straight from the browser via yt-dlp's
  `extract_cookies_from_browser` and feeds it to ytmusicapi as browser auth. Because it
  re-reads each run, the session **never goes stale** while the browser stays logged in (no
  manual re-export). `detect_browser_profiles()` enumerates Firefox-family profiles
  (Firefox, **Zen**, LibreWolf, Waterfox — read via yt-dlp's `firefox` extractor + a
  profile-dir path) plus the Chromium browser names. **Chromium on Windows (Chrome/Edge/
  Brave) is blocked by App-Bound Encryption** (yt-dlp #10927 — `Failed to decrypt with
  DPAPI`); Firefox-family works. Stored as `config.auth_browser` + `auth_browser_profile`.
- **Cookies (manual, expires):** point it at a `cookies.txt` exported from a logged-in
  music.youtube.com; same browser-auth path (SAPISIDHASH) but from a frozen file, so it
  goes stale and must be re-exported. Stored in `config.auth_cookies_file` (NOT
  `cookies_file` — see gotcha below). Built in `youtube._browser_headers_from_cookies`.
  Both browser/cookies share `_headers_from_jar` and send only the ~24 auth-relevant cookie
  names (`_AUTH_COOKIE_NAMES`) — a full-browser dump's ~100 KB Cookie header is rejected by
  YouTube with an empty body.
- **OAuth (device flow) — DEAD, code removed.** Verified empirically against a real
  token: the refresh exchange succeeds but **every `youtubei` call returns `HTTP 400
  INVALID_ARGUMENT`** (6/6 across `get_account_info`/`get_home`/`search`, both WEB_REMIX and
  ANDROID_MUSIC contexts). Google blocks third-party-client OAuth tokens; no client-side fix
  (ytmusicapi 1.12.1 is latest). The whole backend (`login`/`logout`/`OAuthCredentials`,
  `oauth_client_id/secret` config keys) was deleted; only two traces remain: the Account
  screen's "OAuth sign-in was removed" notice, and the boot migration of a stored
  `auth_method='oauth'` to `none` (`App.__init__`).

`youtube.configure_auth(method, cookies_file=auth_cookies_file, browser=, profile=)`
wires the active method at boot; `youtube._get_ytm()` builds the matching `YTMusic`
(cookies/browser → `auth=headers`, else anonymous), degrading
to anonymous on error. For `browser`, extraction happens **inside `_get_ytm()`** (daemon
threads only, under `_ytm_lock`) — never on the UI thread. `auth_status()` labels the footer. `is_authenticated()` is cached (computed once in
`configure_auth`) so the footer/status don't re-parse the cookie file each refresh — but
that cache only reflects whether the file *contains* login cookies, not whether they still
work. So at boot `App._verify_account` (daemon thread) calls `youtube.verify_auth_live()`,
a single live `get_account_info()`: on a **confirmed logout** (cookie/browser auth returns
no account, or ytmusicapi raises a logged-out parse error — `_is_logged_out_error`), it
downgrades `is_authenticated()` to False, clears `config.account_name`, and the UI hides
the `♥ <name>` footer segment + shows a "sign-in expired — press g to re-export" alert.
A transient **network** error is treated as `unknown` (not a logout): the cached name
stays and it re-checks next boot. The `g`-screen `cookies_auth_ok()` likewise reports a
friendly "expired or logged out" message instead of a raw `KeyError`.

**Concurrency + timeouts (anti-hang):** every ytmusicapi call is serialized under
`youtube._ytm_lock` and `_get_ytm()` builds the client once (double-checked) — two boot
threads (`_verify_account` + the For-You feed) otherwise hit the shared `YTMusic`
/`requests.Session` at once and can corrupt a response or deadlock in urllib3. Because a
lock makes one stalled call block all the rest, every `YTMusic` is built via
`_new_ytm()` with a `_TimeoutSession` (`_HTTP_TIMEOUT`=20s default on every request), so
a black-holed YouTube connection raises instead of hanging the app forever. The lock is
only ever taken by daemon threads, never the UI thread.

### Gotcha: auth cookies must NOT reach yt-dlp (two separate cookie files)

`config.auth_cookies_file` (ytmusicapi account auth, set via Account `g`) and
`config.cookies_file` (yt-dlp/mpv **streaming** cookies for age-restricted videos, set via
Settings `s`) are **deliberately separate**. An authenticated YouTube session makes yt-dlp
receive a SABR-only format set it can't play (`Requested format is not available`) → every
track errors → `end-file[reason=error]` cascades the queue song-by-song with **no audio**.
So the player is only ever given `valid_cookies()` (streaming), never the auth cookies.
`App.__init__` has a one-time migration: if `cookies_file` holds a logged-in YTM export
(detected via `_browser_headers_from_cookies`), it's moved to `auth_cookies_file`,
`auth_method`→`cookies`, and `cookies_file` cleared. `_on_track_end` also has a cascade
guard (≥3 sub-2s ends in a row → stop with an error instead of skipping the whole queue).

**Like / save a playlist:** `l` likes the highlighted/playing track; `w` saves the current list as a named playlist (both appear on the home screen)

**Shuffle / repeat:** `z` shuffles the queue; `r` cycles repeat off → one → all

**Resume a session:** pick one from the home screen's **Resume** tab (sessions are saved on quit)

**Manage the library:** on the home screen's Resume / Folders / Liked / Recent tabs,
`d` deletes the highlighted entry (delete playlist / unpin folder / delete session /
unlike / remove-from-recent — playlists, folders and sessions confirm first) and `r`
renames a highlighted saved playlist. Backed by `library.py`
(`delete_playlist`/`rename_playlist`/`unpin_folder`/`delete_session`/`toggle_like`/`remove_recent`).

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
