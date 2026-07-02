# IMPROVEMENTS.md

A living backlog for the YouTube Music TUI: bugs to fix, features to add, and
QOL polish. Grouped by category, roughly ordered by value/effort within each.
Line references point at the current code so each item is actionable.

Status legend: `[ ]` todo · `[x]` done · `[~]` partial / needs follow-up

---

## 1. Bugs / correctness

- [x] **Pause leaks across track changes.** mpv's `pause` property persists
  across `loadfile replace`. Hitting `n` (or selecting a song) while paused
  loaded the new track *paused* while the UI showed ▶ "Playing".
  *Fixed:* `_play_mpv()` now force-resumes (`set_property('pause', False)`) after
  every explicit `loadfile`. (`player.py`)

- [x] **`config.max_results` is dead config.** Now threaded through
  `youtube.resolve(..., max_results=)` and passed from `main._do_search` as
  `self._config.max_results`.

- [~] **ffplay fallback has no transport controls.** Still no position/seek/
  volume with ffplay, but the app now shows a "Using ffplay (limited controls)"
  status on start, and ffplay auto-advance is fixed (see below). Full controls
  remain mpv-only by design.

- [x] **IPC-failure fallback loses the player.** The one-shot `mpv … url` path
  now spawns a watcher thread that fires `on_end` on exit (auto-advance works),
  and honors a resume `--start=+N`. (`player.py:_play_mpv`)

- [x] **Volume thrashes the config file.** Added `Config.update()`/`flush()`;
  volume and theme changes now update in memory and flush via a 1s debounced
  timer (`main._schedule_config_flush`) + on quit.

- [x] **Progressive playlist load can stomp an in-progress filter.**
  `_populate_results(..., keep_filter=True)` preserves the active filter when the
  full playlist lands.

- [~] **Unix socket cleanup can race / unlink the wrong file.** Endpoint is
  PID-unique; left best-effort. Low-risk, untouched.

- [x] **`stop()`/`_play_mpv()` locking is inconsistent.** `play()` now runs the
  start path under `self._lock`; `stop()` split into `_stop_locked()` so both
  share consistent locking. (`player.py`)

---

## 2. New features

- [x] **Persistent playlists / favorites.** New `library.py` stores liked songs,
  named playlists, pinned folders, and recent plays; surfaced on the boot
  **home screen** (Folders / Liked / Recent). `l` likes, `w` saves a playlist.

- [x] **Play history + "recently played".** `library.add_recent()` on every play;
  shown in the home screen's Recent tab.

- [x] **Shuffle & repeat.** `z` shuffles the queue (keeping current track first),
  `r` cycles repeat off/one/all; honored by `_on_track_end`/`action_next_track`,
  persisted in sessions.

- [x] **Resume playback position.** Sessions saved on quit (queue + position +
  shuffle/repeat); home screen "Resume" dropdown restores and seeks via
  `Player.play(url, start=)` (mpv `file-loaded` seek).

- [~] **Now-Playing / lyrics view.** *Shipped the lyrics half:* `LyricsScreen`
  with time-synced follow (highlight + centered auto-scroll) and on-demand
  whole-text translation (`t` toggle, `g` language). Lyrics are fetched with an
  anonymous client (`youtube.ytm_lyrics` — signed-in auth 400s on the timestamps
  endpoint). Remaining: the full-screen now-playing face (big title, ASCII album
  art, wide progress bar).

- [x] **Album / artist browse.** Search results now prepend `◆` artist and `◇`
  album rows (`ytm_search_entities` with `filter='artists'/'albums'` for correct
  ranking); artists open an `ArtistScreen` (songs/albums/singles/videos), albums
  open into the queue.

- [ ] **Sleep timer.** "Stop after N minutes / after this track." Small timer +
  `self._player.quit()`/`stop()`.

- [ ] **Gapless / crossfade hint.** mpv supports `--gapless-audio`; expose as a
  config toggle for album listening.

- [ ] **Offline: watch folder / rescan key.** A `R` rebind to rescan the current
  local folder without re-typing the path, plus optional caching of scanned tags
  (mutagen scan of a big library is slow on every load). (`offline.py`)

- [x] **Library management UI.** Home screen tabs (Resume / Folders / Liked /
  Recent) now support `d` delete and `R` rename: `d` deletes the highlighted entry
  (delete playlist / unpin folder / delete session — confirmed; unlike /
  remove-from-recent — instant) and `R` renames a saved playlist. Sessions moved
  from the old dropdown into a **Resume tab** so they manage uniformly. Added
  `library.rename_playlist` / `remove_recent` / `clear_recent`. (`main.HomeScreen`)

- [ ] **Append to / overwrite-confirm playlists.** `save_playlist(name, …)`
  silently overwrites a same-named playlist. Add "append to existing playlist"
  and confirm before clobbering. (`library.save_playlist`, `main.action_save_playlist`)

- [ ] **Queue editing: reorder + remove.** In queue view, `J`/`K` to move the
  highlighted track up/down and `d` to remove it. Complements `p` (play-next),
  which is the only queue edit today. (`main` queue actions)

- [x] **Radio / endless mix.** `∞` radio seeds an endless mix from the current
  track via `get_watch_playlist(radio=True)` and replaces the queue.

- [ ] **Play a playlist shuffled from home.** Selecting a Folders entry could
  offer "play shuffled" directly, not just load into the library view.

- [ ] **Export / import library.** `library.json` is already portable JSON — a
  small export/import (or just documenting that copying the file moves your
  playlists between machines) makes it shareable across your Windows/Mac/Linux boxes.

---

## 3. Quality-of-life

- [x] **Visible "stop" / clear.** `x` stops playback and clears "now playing".

- [ ] **Jump to now-playing.** A key (`g`) to scroll the table to the currently
  playing track, useful in long playlists.

- [ ] **Click / mouse seek on the progress bar.** Textual supports mouse; let a
  click on `#progress-row` seek to that fraction of the track.

- [x] **Playing-row highlight.** The currently-playing track is marked ▶ and
  styled with the theme accent in both library and queue views.

- [x] **Show queue length / position** in the player bar (`Queue 3/120`) and the
  footer info bar.

- [x] **Settings `~` expansion + validation.** `SettingsScreen` expands `~`/env
  vars and shows live ✓/✗ for the cookies file and folder; `config.valid_cookies`
  and `offline.scan_folder` also expand.

- [x] **Remember last mode (online/offline)** across launches via `config.app_mode`.

- [x] **Confirm-on-quit when something is playing.** `q` shows a Yes/No modal
  (and saves the session) while a track is playing.

- [x] **Help overlay.** All footer key hints removed; `?` opens a full
  `KeybindingsScreen` listing every shortcut. A custom footer info bar replaces
  the default Footer with mode/source/shuffle/repeat/queue/volume/theme.

- [ ] **Status line auto-clears.** Transient messages ("Added to queue: …")
  linger forever. Auto-revert to a default after ~4s via `set_timer`.

- [ ] **Remember last query** across launches (last mode is now remembered).

- [ ] **Loading spinner / indeterminate progress** during search and big
  playlist fetches, instead of a static "Loading…" string.

- [ ] **Liked indicator in rows.** Show a `♥` marker next to tracks already in
  the liked set (library has `is_liked()`), so `l` toggling is visible at a glance.
  (`main._render_table`)

---

## 4. Robustness / cross-platform

- [ ] **Graceful network errors.** ytmusicapi/yt-dlp failures surface as raw
  `Search error: <exception>`. Detect offline/no-network and show a friendly
  message; consider a short retry.

- [ ] **mpv version / capability check** at startup (warn if very old mpv lacks
  JSON IPC).

- [ ] **Windows: handle mpv from `scoop`/`winget` PATH refresh.** If mpv was just
  installed, `shutil.which` may miss it until terminal restart — mention in the
  no-backend status message. (`player.py:42`, `main.py:343`)

- [x] **Avoid `/tmp` hard-code on Unix where unsuitable.** `player._unix_socket_path()`
  now prefers `/tmp` (short → under the AF_UNIX ~104-char limit) but falls back to
  `$TMPDIR` / `tempfile.gettempdir()` when `/tmp` isn't writable — fixes Termux/Android
  (no writable `/tmp`) so mpv IPC + transport controls work there. (`player.py`)

- [ ] **Mobile / "host it on the phone itself" (research, 2026-06-25).**
  - **Android via Termux is the viable native path.** `pkg install python mpv
    ffmpeg` → `pip install -r requirements.txt` → `python main.py`. The real
    Textual TUI runs in the Termux terminal with audio out the phone speakers;
    `_find_ytdlp()` finds Termux's yt-dlp on `$PREFIX/bin` automatically.
  - **Socket-path blocker: FIXED.** `player._unix_socket_path()` now falls back
    to `$TMPDIR`/`tempfile.gettempdir()` when `/tmp` isn't writable, so mpv IPC +
    transport controls work on Termux. (May still want an mpv `--ao` nudge —
    opensles/pulse — if a given device has no default audio out.)
  - **iOS:** not viable natively (no mpv, restricted audio/background; iSH/a-Shell
    can't run the mpv streaming path). Only a thin client to a remote box.
  - **`textual serve`** (browser/touch UI) is a possible later phase, but the
    Python+mpv process still has to run locally (Termux) to be "on the phone."

- [ ] **Atomic JSON writes.** `config.py` / `library.py` write JSON in place; a
  crash mid-write (or two writers) can truncate the file. Write to a temp file and
  `os.replace()` it into position. (`config._save`, `library._save`)

- [ ] **Library writes happen from threads.** `add_recent()` (main thread) and
  `pin_folder()` (scan thread) both write `library.json`; harmless today but a
  shared lock (or routing all writes through the event loop) would be safer.

- [ ] **Periodic session autosave.** Sessions are saved only on a clean quit, so
  a crash/`kill` loses resume state. Snapshot every ~30s via `set_interval` too.
  (`main._save_session`)

---

## 5. Code health / tests

- [ ] **Commit the headless smoke tests as `tests/`.** The Textual `run_test`
  scripts written during the home-screen/feature pass (home flow, populate/render,
  footer, `?`, shuffle/repeat, resume-with-seek, repeat-all wrap, save-playlist,
  confirm-quit, session save) were throwaway — port them to `pytest` with a stub
  player so they run in CI without mpv.

- [ ] **Unit tests for queue logic.** `add_queue`, `play_next`, auto-advance,
  and filter→master-index mapping (`_visible_results`/`_highlighted_track`) are
  pure-ish and very testable without a real mpv.

- [ ] **Transport line-splitting test.** Feed `b'{"a":1}\n{"b":2}\n'` to
  `_UnixSocketTransport._pop_line` in pieces (the plan already called for this) so
  the parser is exercised on Windows too. (`player.py:146`)

- [ ] **Type hints + a `track` TypedDict.** Every layer passes the same
  `{id,title,uploader,duration,url,thumbnail}` dict — formalize it to catch shape
  drift between `youtube.py`, `offline.py`, and `main.py`.

- [ ] **Pin/loosen deps intentionally.** `requirements.txt` mixes pinned and
  unpinned; document the yt-dlp "must be recent" constraint there too (it's only
  in CLAUDE.md right now).

- [ ] **Extract magic numbers.** Poll interval (1.0s), seek step (10s), volume
  step (5%), progress-bar width (50) are scattered — pull into module constants.

---

## Suggested next-up (highest value / lowest risk)

Shipped since the last pass: timed **lyrics + translation**, **artist/album
browse**, **radio (endless mix)**, the **stuck-fetch fix** (yt-dlp socket
timeouts + selection debounce + load watchdog), and the OAuth dead-code removal.
Remaining high-value / low-risk picks:

1. **Liked indicator in rows** + **status line auto-clear** (§3) — small, daily.
2. **Atomic JSON writes** + **library write lock** (§4) — cheap insurance
   against corrupting config/library (two threads write library.json today).
3. **Queue editing: reorder + remove** (§2) — rounds out queue control.
4. **Commit the headless tests as `tests/`** (§5) — locks in current behavior.
5. **Full-screen now-playing face** (§2 [~]) — the remaining half of the
   lyrics/now-playing headline feature.
