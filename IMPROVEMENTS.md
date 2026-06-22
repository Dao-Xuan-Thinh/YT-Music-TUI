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

- [ ] **`config.max_results` is dead config.** `config.py` exposes `max_results`
  (default 15) but `main.py`/`youtube.py` never pass it — search is hard-coded to
  `max_results=15` in `youtube.resolve()`/`search()`. Either wire it through
  (`youtube.resolve(query, ..., max_results=self._config.max_results)`) or drop
  the key. (`main.py:394`, `youtube.py:147`, `config.py:74`)

- [ ] **ffplay fallback has no transport controls.** With ffplay (no mpv),
  `get_position`/`get_duration` always return `0.0`, and `seek`/`set_volume`/
  `pause` are no-ops — the progress bar never moves and `space`/`←→`/`+/-` do
  nothing. At minimum, surface "limited controls (ffplay)" in the status line so
  it doesn't look broken. (`player.py:431`, `player.py:529-537`)

- [ ] **IPC-failure fallback loses the player.** When `_ipc` can't connect,
  `_play_mpv()` shells out to a one-shot `mpv … url` (`player.py:419`). That
  process reports no position, ignores pause/seek/volume, and never fires
  `on_end` (no auto-advance). Consider retrying the daemon, or wiring the
  one-shot's `.wait()` to `on_end` like the ffplay path does.

- [ ] **Volume thrashes the config file.** Every `+`/`-` keypress calls
  `_apply_volume()` → `config.volume` setter → `save()` → full JSON rewrite
  (`main.py:756`, `config.py:58`). Debounce: save on quit / after a short idle,
  not on every keystroke. Same applies to rapid theme cycling.

- [ ] **Progressive playlist load can stomp an in-progress filter.** The full
  fetch in `_do_load_playlist()` calls `_populate_results()`, which resets
  `_filter_text` and `view_mode` (`main.py:420`, `main.py:465`). If the user
  starts filtering while "fetching the rest…", their filter is wiped when the
  full list lands. Re-apply the current filter instead of clearing.

- [ ] **Unix socket cleanup can race / unlink the wrong file.** `close()`
  `os.unlink(_CONNECT_TARGET)` unconditionally if the path exists
  (`player.py:176`). Since the endpoint is PID-unique this is low-risk, but mpv
  usually owns that file — only unlink sockets we know mpv has exited from.

- [ ] **`stop()`/`_play_mpv()` locking is inconsistent.** `stop()` takes
  `self._lock` but `play()`/`_play_mpv()`/`_ensure_mpv_running()` don't, so a
  `stop` racing a `play` is theoretically unsafe (`player.py:474` vs `399`).
  Low priority given single-user TUI, but worth tidying.

---

## 2. New features

- [ ] **Persistent playlists / favorites.** Save the current queue (or a "liked"
  set) to disk and reload it — a `~/.config/yttui/playlists/*.json` store. Makes
  the app useful beyond a single session.

- [ ] **Play history + "recently played".** Append played tracks to a history
  file; add a view to replay them. Pairs naturally with the queue/library view
  toggle already in place (`view_mode`).

- [ ] **Shuffle & repeat.** `shuffle` (randomize queue order) and
  `repeat` (off / one / all) — both purely queue-side logic in `main.py`, work
  identically online and offline. Add `r` (repeat cycle) and `z` (shuffle).

- [ ] **Resume playback position.** Persist `current_url` + position on quit;
  offer to resume on next launch. mpv already reports `time-pos`.

- [ ] **Lyrics / metadata panel.** Optional side panel showing album/year/
  thumbnail (ASCII or via terminal image protocol). ytmusicapi returns album +
  thumbnails already (`youtube.py:_ytm_track_to_dict`).

- [ ] **Album / artist browse.** ytmusicapi supports `get_album`,
  `get_artist`, `get_watch_playlist` (radio). A "browse" mode would go well
  beyond plain search.

- [ ] **Sleep timer.** "Stop after N minutes / after this track." Small timer +
  `self._player.quit()`/`stop()`.

- [ ] **Gapless / crossfade hint.** mpv supports `--gapless-audio`; expose as a
  config toggle for album listening.

- [ ] **Offline: watch folder / rescan key.** A `R` rebind to rescan the current
  local folder without re-typing the path, plus optional caching of scanned tags
  (mutagen scan of a big library is slow on every load). (`offline.py`)

---

## 3. Quality-of-life

- [ ] **Visible "stop" / clear.** There's `stop()` in the player but no binding —
  add `.` or `x` to stop and clear "now playing".

- [ ] **Jump to now-playing.** A key (`g`) to scroll the table to the currently
  playing track, useful in long playlists.

- [ ] **Click / mouse seek on the progress bar.** Textual supports mouse; let a
  click on `#progress-row` seek to that fraction of the track.

- [ ] **Status line auto-clears.** Transient messages ("Added to queue: …")
  linger forever. Auto-revert to a default after ~4s via `set_timer`.

- [ ] **Show queue length / position in the player bar.** e.g. `3/120` so the
  user knows where they are without switching to queue view.

- [ ] **Confirm-on-quit when something is playing** (optional toggle), to avoid
  accidental `q`.

- [ ] **Settings: `~` expansion + validation.** Cookie/folder paths typed with
  `~` aren't expanded (`config.py` stores them raw; `valid_cookies()` does a bare
  `os.path.isfile`). Run paths through `os.path.expanduser` and show a ✓/✗ in the
  Settings modal. (`config.py:104`, `main.py:766`)

- [ ] **Help overlay.** A `?` modal listing all keybindings (the Footer only
  shows `show=True` ones; `+/-`, `←→`, `C`, `escape` are hidden).

- [ ] **Remember last mode (online/offline) and last query** across launches.

- [ ] **Loading spinner / indeterminate progress** during search and big
  playlist fetches, instead of a static "Loading…" string.

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

- [ ] **Avoid `/tmp` hard-code on Unix where unsuitable.** `/tmp` is correct for
  the AF_UNIX path-length limit, but on locked-down systems consider
  `$XDG_RUNTIME_DIR` when it's short enough. (`player.py:38`)

---

## 5. Code health / tests

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

1. Wire up `max_results` or remove it (§1).
2. Debounce config writes (§1).
3. Shuffle + repeat (§2) — small, high daily value, works in both modes.
4. Help overlay `?` + auto-clearing status line (§3).
5. `~` expansion & path validation in Settings (§3).
