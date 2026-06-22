"""
YouTube Music TUI — main.py
Lightweight terminal YouTube Music player.

Keybindings:
  /         Focus search bar
  f         Filter the loaded list (Esc to clear)
  Enter     Play selected track
  Space     Pause / Resume
  n         Next in queue
  a         Add highlighted track to queue
  p         Play highlighted track next (after current)
  Q         Toggle Library / Queue view
  t         Cycle search source  (YTM → YT → Both)  [online mode only]
  o         Toggle online / offline mode
  c         Theme picker  ·  C  Cycle theme
  + / -     Volume up / down
  ← / →     Seek ±10s
  s         Open settings (cookies file + local audio folder)
  q         Quit
"""

import os
import threading
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label, OptionList, Static
)
from textual.widgets.option_list import Option
from textual.screen import ModalScreen

import youtube
import player as player_module
from config import Config


# ── Helpers ───────────────────────────────────────────────────────────────────

SOURCE_CYCLE = ['ytm', 'yt', 'both']
SOURCE_LABEL = {'ytm': 'YT Music', 'yt': 'YouTube', 'both': 'Both'}

# Curated "cool" themes for quick-cycle (subset of Textual's built-ins)
THEME_CYCLE = [
    'tokyo-night', 'dracula', 'catppuccin-mocha', 'gruvbox', 'nord',
    'rose-pine', 'monokai', 'flexoki', 'solarized-dark', 'catppuccin-macchiato',
]

# OS-aware example paths for settings placeholders
if os.name == 'nt':
    _EG_COOKIES = 'e.g. C:\\Users\\you\\cookies.txt'
    _EG_FOLDER  = 'e.g. C:\\Users\\you\\Music'
else:
    _EG_COOKIES = 'e.g. ~/cookies.txt'
    _EG_FOLDER  = 'e.g. ~/Music'

def _fmt(seconds):
    if not seconds:
        return '--:--'
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f'{h}:{m:02d}:{sec:02d}' if h else f'{m}:{sec:02d}'

def _bar(pos, dur, width=40):
    if not dur:
        return '─' * width
    filled = int(width * pos / dur)
    return '█' * filled + '─' * (width - filled)


# ── Settings screen ───────────────────────────────────────────────────────────

class SettingsScreen(ModalScreen):
    """Modal for setting cookies file path and local audio folder."""
    BINDINGS = [Binding('escape', 'dismiss_modal', 'Close')]

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    CSS = """
    SettingsScreen {
        align: center middle;
    }
    #settings-box {
        width: 70;
        height: 16;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #settings-box Label { margin-bottom: 1; }
    #settings-box Input { margin-bottom: 1; }
    #btn-row { height: 3; }
    """

    def __init__(self, current_cookies='', current_folder=''):
        super().__init__()
        self._current_cookies = current_cookies
        self._current_folder  = current_folder

    def compose(self) -> ComposeResult:
        with Vertical(id='settings-box'):
            yield Label('Cookies file path (Netscape format .txt):')
            yield Input(value=self._current_cookies, id='cookies-input',
                        placeholder=_EG_COOKIES)
            yield Label('Local audio folder (for offline mode — press o):')
            yield Input(value=self._current_folder, id='folder-input',
                        placeholder=_EG_FOLDER)
            with Horizontal(id='btn-row'):
                yield Button('Save', id='btn-save', variant='primary')
                yield Button('Cancel', id='btn-cancel')

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'btn-save':
            cookies = self.query_one('#cookies-input', Input).value.strip()
            folder  = self.query_one('#folder-input',  Input).value.strip()
            self.dismiss({'cookies': cookies, 'folder': folder})
        else:
            self.dismiss(None)


# ── Theme picker screen ───────────────────────────────────────────────────────

class ThemePickerScreen(ModalScreen):
    """Modal listing all built-in themes with live preview on highlight."""
    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]

    CSS = """
    ThemePickerScreen {
        align: center middle;
    }
    #theme-box {
        width: 50;
        height: 24;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #theme-box Label { margin-bottom: 1; text-style: bold; }
    #theme-list { height: 1fr; }
    """

    def __init__(self, current_theme, theme_names):
        super().__init__()
        self._original_theme = current_theme
        self._theme_names = theme_names

    def compose(self) -> ComposeResult:
        with Vertical(id='theme-box'):
            yield Label('Theme  (↑↓ preview · Enter apply · Esc cancel)')
            options = [Option(name, id=name) for name in self._theme_names]
            yield OptionList(*options, id='theme-list')

    def on_mount(self) -> None:
        ol = self.query_one('#theme-list', OptionList)
        if self._original_theme in self._theme_names:
            ol.highlighted = self._theme_names.index(self._original_theme)
        ol.focus()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        # Live preview
        if event.option.id:
            self.app.theme = event.option.id

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        # Revert live preview
        self.app.theme = self._original_theme
        self.dismiss(None)


# ── Main App ──────────────────────────────────────────────────────────────────

class YTMApp(App):
    """YouTube Music TUI."""

    TITLE = 'YouTube Music TUI'

    CSS = """
    Screen {
        layout: vertical;
    }

    /* ── Search bar row ── */
    #search-row {
        height: 3;
        padding: 0 1;
        background: $panel;
    }
    #search-input {
        width: 1fr;
    }
    #source-btn {
        width: 12;
        margin-left: 1;
    }

    /* ── Filter row (hidden until toggled) ── */
    #filter-row {
        height: 3;
        padding: 0 1;
        background: $boost;
        display: none;
    }
    #filter-row.visible {
        display: block;
    }
    #filter-input {
        width: 1fr;
    }

    /* ── Results table ── */
    #results-table {
        height: 1fr;
        border: none;
    }

    /* ── Player bar ── */
    #player-bar {
        height: 5;
        padding: 0 2;
        background: $panel;
        border-top: solid $accent;
    }
    #now-playing {
        height: 1;
        color: $text;
        text-style: bold;
    }
    #controls-row {
        height: 1;
        color: $text-muted;
    }
    #progress-row {
        height: 1;
        color: $accent;
    }
    #status-row {
        height: 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding('slash', 'focus_search', 'Search', show=True),
        Binding('f', 'filter', 'Filter', show=True),
        Binding('space', 'toggle_pause', 'Pause/Resume', show=True),
        Binding('n', 'next_track', 'Next', show=True),
        Binding('a', 'add_queue', '+Queue', show=True),
        Binding('p', 'play_next', 'Play next', show=True),
        Binding('Q', 'toggle_view', 'Queue/Library', show=True),
        Binding('t', 'cycle_source', 'Source', show=True),
        Binding('o', 'toggle_mode', 'Online/Offline', show=True),
        Binding('c', 'theme_picker', 'Theme', show=True),
        Binding('C', 'cycle_theme', 'Cycle theme', show=False),
        Binding('plus,equal', 'vol_up', 'Vol+', show=False),
        Binding('minus', 'vol_down', 'Vol-', show=False),
        Binding('left', 'seek_back', 'Seek-', show=False),
        Binding('right', 'seek_fwd', 'Seek+', show=False),
        Binding('s', 'settings', 'Settings', show=True),
        Binding('escape', 'clear_filter', 'Clear filter', show=False),
        Binding('q', 'quit', 'Quit', show=True),
    ]

    # Reactive state
    search_source: reactive[str] = reactive('ytm')
    app_mode: reactive[str]      = reactive('online')   # 'online' or 'offline'
    view_mode: reactive[str]     = reactive('library')  # 'library' or 'queue'
    now_playing: reactive[str]   = reactive('')
    position: reactive[float]    = reactive(0.0)
    duration: reactive[float]    = reactive(0.0)
    is_paused: reactive[bool]    = reactive(False)
    status_msg: reactive[str]    = reactive('Ready — press / to search')
    volume: reactive[int]        = reactive(80)

    def __init__(self):
        super().__init__()
        self._config  = Config()
        self._player  = player_module.Player(
            cookies_file=self._config.valid_cookies()
        )
        self._player.set_on_end(self._on_track_end)
        self._results  = []   # list of track dicts from last search/scan
        self._queue    = []   # list of track dicts to play next
        self._queue_idx = -1
        self._filter_text = ''
        self.search_source = self._config.search_source
        self.volume        = self._config.volume
        self._poll_timer   = None

    # ── Layout ────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id='search-row'):
            yield Input(
                placeholder='Search or paste URL…',
                id='search-input',
            )
            yield Button(
                SOURCE_LABEL[self.search_source],
                id='source-btn',
                variant='default',
            )
        with Horizontal(id='filter-row'):
            yield Input(
                placeholder='Filter loaded list… (Esc to clear)',
                id='filter-input',
            )
        yield DataTable(id='results-table', cursor_type='row')
        with Vertical(id='player-bar'):
            yield Static('♪  Nothing playing', id='now-playing')
            yield Static('', id='controls-row')
            yield Static('', id='progress-row')
            yield Static(self.status_msg, id='status-row')
        yield Footer()

    def on_mount(self) -> None:
        # Apply saved theme
        try:
            self.theme = self._config.theme
        except Exception:
            pass
        tbl = self.query_one('#results-table', DataTable)
        tbl.add_column('#',        width=4)
        tbl.add_column('Title',    width=45)
        tbl.add_column('Artist',   width=25)
        tbl.add_column('Duration', width=8)
        self._poll_timer = self.set_interval(1.0, self._poll_player)
        # Pre-start mpv in background so first play has no startup delay
        threading.Thread(target=self._init_player, daemon=True).start()

    def _init_player(self) -> None:
        if self._player.backend is None:
            self.call_from_thread(
                self._set_status,
                'No audio backend found — install mpv (macOS: brew install mpv) to enable playback.'
            )
            return
        self._player._ensure_mpv_running()
        self._apply_volume()

    # ── Search / Scan ─────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == 'filter-input':
            # Enter in filter keeps the filter applied and returns to the list
            self.query_one('#results-table', DataTable).focus()
            return
        if event.input.id != 'search-input':
            return
        query = event.value.strip()
        if not query:
            return
        if self.app_mode == 'offline':
            self._config.local_folder = query
            self._do_scan_folder(query)
        else:
            self._do_search(query)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == 'filter-input':
            self._filter_text = event.value
            if self.view_mode != 'library':
                self.view_mode = 'library'
            self._render_table()
            self._set_status(
                f'{len(self._visible_results())} match(es) — Enter on a song to play'
                if self._filter_text.strip() else 'Filter cleared'
            )

    def _do_search(self, query: str) -> None:
        # YouTube Music playlist URLs load progressively (first page, then all)
        playlist_id = youtube.ytm_playlist_id(query)
        if playlist_id:
            self._do_load_playlist(playlist_id)
            return

        self._set_status(f'Searching "{query}"…')
        self._results = []

        def _run():
            try:
                results = youtube.resolve(
                    query,
                    source=self.search_source,
                    cookies_file=self._config.valid_cookies(),
                )
                self.call_from_thread(self._populate_results, results)
            except Exception as exc:
                self.call_from_thread(self._set_status, f'Search error: {exc}')

        threading.Thread(target=_run, daemon=True).start()

    def _do_load_playlist(self, playlist_id: str) -> None:
        """Load a large YouTube Music playlist: show first page fast, then all."""
        self._set_status('Loading playlist… first tracks')
        self._results = []

        def _run():
            try:
                first = youtube.ytm_playlist(playlist_id, limit=100)
                if first:
                    self.call_from_thread(self._populate_results, first)
                    self.call_from_thread(
                        self._set_status,
                        f'{len(first)} tracks loaded — fetching the rest…'
                    )
                full = youtube.ytm_playlist(playlist_id, limit=None)
                self.call_from_thread(self._populate_results, full)
            except Exception as exc:
                self.call_from_thread(self._set_status, f'Playlist error: {exc}')

        threading.Thread(target=_run, daemon=True).start()

    def _do_scan_folder(self, path: str) -> None:
        self._set_status(f'Scanning {path}…')
        self._results = []

        def _run():
            try:
                from offline import scan_folder
                results = scan_folder(path)
                self.call_from_thread(self._populate_results, results)
                if not results:
                    self.call_from_thread(
                        self._set_status,
                        f'No audio files found in: {path}'
                    )
            except Exception as exc:
                self.call_from_thread(self._set_status, f'Scan error: {exc}')

        threading.Thread(target=_run, daemon=True).start()

    def _populate_results(self, results) -> None:
        self._results = results
        self._filter_text = ''
        self.view_mode = 'library'
        self._render_table()
        if not results:
            self._set_status('No results found.')
            return
        mode_label = 'file(s)' if self.app_mode == 'offline' else 'result(s)'
        self._set_status(f'{len(results)} {mode_label} — Enter to play')
        self.query_one('#results-table', DataTable).focus()

    # ── Table rendering ───────────────────────────────────────────────────

    def _visible_results(self):
        """Return [(master_idx, track), …] for the library view, honoring filter."""
        ft = self._filter_text.lower().strip()
        out = []
        for i, r in enumerate(self._results):
            if ft:
                hay = (r.get('title', '') + ' ' + r.get('uploader', '')).lower()
                if ft not in hay:
                    continue
            out.append((i, r))
        return out

    def _render_table(self) -> None:
        """Render the DataTable for the current view_mode (+ filter in library)."""
        tbl = self.query_one('#results-table', DataTable)
        tbl.clear()
        if self.view_mode == 'queue':
            for qi, r in enumerate(self._queue):
                marker = '▶' if qi == self._queue_idx else str(qi + 1)
                dur = _fmt(r['duration']) if r['duration'] else '?'
                tbl.add_row(marker, r['title'], r['uploader'], dur, key=f'q{qi}')
        else:
            for master_idx, r in self._visible_results():
                dur = _fmt(r['duration']) if r['duration'] else '?'
                tbl.add_row(str(master_idx + 1), r['title'], r['uploader'],
                            dur, key=str(master_idx))

    def _highlighted_track(self):
        """Return (kind, index, track) for the row under the cursor.

        kind is 'library' (index = master index into _results) or
        'queue' (index = index into _queue). Returns None if no row.
        """
        tbl = self.query_one('#results-table', DataTable)
        try:
            row = tbl.cursor_row
            key = tbl.coordinate_to_cell_key((row, 0)).row_key.value
        except Exception:
            return None
        if key is None:
            return None
        if self.view_mode == 'queue':
            qi = int(key[1:])  # strip leading 'q'
            if 0 <= qi < len(self._queue):
                return ('queue', qi, self._queue[qi])
        else:
            mi = int(key)
            if 0 <= mi < len(self._results):
                return ('library', mi, self._results[mi])
        return None

    # ── Playback ──────────────────────────────────────────────────────────

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        if key is None:
            return
        if self.view_mode == 'queue':
            qi = int(key[1:])  # 'q{idx}'
            if 0 <= qi < len(self._queue):
                self._play_queue_item(qi)
        else:
            idx = int(key)
            if idx < len(self._results):
                # Replace queue with remaining results starting from selection
                self._queue = self._results[idx:]
                self._queue_idx = 0
                self._play_queue_item(0)

    def _play_queue_item(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._queue):
            return
        track = self._queue[idx]
        self._queue_idx = idx
        self.now_playing = f'{track["title"]}  —  {track["uploader"]}'
        self._set_status('Loading…')
        if self.view_mode == 'queue':
            self._render_table()
        url = track['url']

        def _run():
            try:
                self._player.play(url)
                self.call_from_thread(self._set_status, 'Playing')
            except Exception as exc:
                self.call_from_thread(self._set_status, f'Playback error: {exc}')

        threading.Thread(target=_run, daemon=True).start()

    def _on_track_end(self) -> None:
        """Called by player when a track finishes."""
        next_idx = self._queue_idx + 1
        if next_idx < len(self._queue):
            self.call_from_thread(self._play_queue_item, next_idx)
        else:
            self.call_from_thread(self._set_status, 'Queue finished')
            self.call_from_thread(setattr, self, 'now_playing', '')

    # ── Player polling ────────────────────────────────────────────────────

    def _poll_player(self) -> None:
        self.position  = self._player.get_position()
        self.duration  = self._player.get_duration()
        self.is_paused = self._player.is_paused()
        self._update_player_bar()

    def _update_player_bar(self) -> None:
        pos = self.position
        dur = self.duration

        pause_icon = '❚❚' if self.is_paused else '▶'
        controls = f'◀◀  {pause_icon}  ▶▶   Vol: {self.volume}%   {_fmt(pos)} / {_fmt(dur)}'
        bar      = _bar(pos, dur, width=50)

        try:
            self.query_one('#now-playing',   Static).update(
                f'♪  {self.now_playing}' if self.now_playing else '♪  Nothing playing'
            )
            self.query_one('#controls-row',  Static).update(controls)
            self.query_one('#progress-row',  Static).update(bar)
        except NoMatches:
            pass

    def _set_status(self, msg: str) -> None:
        self.status_msg = msg
        try:
            self.query_one('#status-row', Static).update(msg)
        except NoMatches:
            pass

    def _update_mode_ui(self) -> None:
        """Update source button label and search input placeholder for current mode."""
        try:
            inp = self.query_one('#search-input', Input)
            btn = self.query_one('#source-btn', Button)
            if self.app_mode == 'offline':
                inp.placeholder = 'Local folder path…'
                btn.label = 'OFFLINE'
            else:
                inp.placeholder = 'Search or paste URL…'
                btn.label = SOURCE_LABEL[self.search_source]
        except NoMatches:
            pass

    # ── Actions ───────────────────────────────────────────────────────────

    def action_focus_search(self) -> None:
        self.query_one('#search-input', Input).focus()

    def action_toggle_pause(self) -> None:
        self._player.toggle_pause()

    def action_next_track(self) -> None:
        self._play_queue_item(self._queue_idx + 1)

    # ── Queue ─────────────────────────────────────────────────────────────

    def action_add_queue(self) -> None:
        hit = self._highlighted_track()
        if not hit:
            return
        _, _, track = hit
        self._queue.append(track)
        if not self.now_playing:
            # Nothing playing — start the track we just added
            self._queue_idx = len(self._queue) - 1
            self._play_queue_item(self._queue_idx)
        else:
            self._set_status(
                f'Added to queue: {track["title"]}  ({len(self._queue)} queued)'
            )
            if self.view_mode == 'queue':
                self._render_table()

    def action_play_next(self) -> None:
        hit = self._highlighted_track()
        if not hit:
            return
        _, _, track = hit
        if not self.now_playing or not self._queue:
            # Nothing playing — just start it
            self._queue.append(track)
            self._queue_idx = len(self._queue) - 1
            self._play_queue_item(self._queue_idx)
        else:
            self._queue.insert(self._queue_idx + 1, track)
            self._set_status(f'Plays next: {track["title"]}')
        if self.view_mode == 'queue':
            self._render_table()

    def action_toggle_view(self) -> None:
        if self.view_mode == 'library':
            self.view_mode = 'queue'
            self._render_table()
            self._set_status(
                f'Queue view — {len(self._queue)} track(s). Q to go back'
                if self._queue else 'Queue is empty — Q to go back'
            )
        else:
            self.view_mode = 'library'
            self._render_table()
            self._set_status('Library view')
        self.query_one('#results-table', DataTable).focus()

    # ── Filter ────────────────────────────────────────────────────────────

    def action_filter(self) -> None:
        row = self.query_one('#filter-row', Horizontal)
        row.add_class('visible')
        self.query_one('#filter-input', Input).focus()
        self._set_status('Type to filter the loaded list — Esc to clear')

    def action_clear_filter(self) -> None:
        row = self.query_one('#filter-row', Horizontal)
        if not row.has_class('visible'):
            return
        row.remove_class('visible')
        self.query_one('#filter-input', Input).value = ''
        self._filter_text = ''
        self._render_table()
        self.query_one('#results-table', DataTable).focus()

    # ── Themes ────────────────────────────────────────────────────────────

    def action_cycle_theme(self) -> None:
        cur = self.theme
        idx = THEME_CYCLE.index(cur) if cur in THEME_CYCLE else -1
        new = THEME_CYCLE[(idx + 1) % len(THEME_CYCLE)]
        self.theme = new
        self._config.theme = new
        self._set_status(f'Theme: {new}')

    def action_theme_picker(self) -> None:
        names = sorted(self.available_themes.keys())

        def _after(chosen):
            if chosen:
                self.theme = chosen
                self._config.theme = chosen
                self._set_status(f'Theme: {chosen}')

        self.push_screen(ThemePickerScreen(self.theme, names), _after)

    def action_toggle_mode(self) -> None:
        if self.app_mode == 'online':
            self.app_mode = 'offline'
            self._update_mode_ui()
            folder = self._config.local_folder
            if folder:
                self._do_scan_folder(folder)
            else:
                self._set_status('Offline mode — press s to set local folder, or type path and Enter')
                self.query_one('#search-input', Input).focus()
        else:
            self.app_mode = 'online'
            self._update_mode_ui()
            self._set_status('Online mode — press / to search')

    def action_cycle_source(self) -> None:
        if self.app_mode == 'offline':
            return
        idx = SOURCE_CYCLE.index(self.search_source)
        self.search_source = SOURCE_CYCLE[(idx + 1) % len(SOURCE_CYCLE)]
        self._config.search_source = self.search_source
        try:
            self.query_one('#source-btn', Button).label = SOURCE_LABEL[self.search_source]
        except NoMatches:
            pass

    def action_vol_up(self) -> None:
        self.volume = min(100, self.volume + 5)
        self._apply_volume()

    def action_vol_down(self) -> None:
        self.volume = max(0, self.volume - 5)
        self._apply_volume()

    def _apply_volume(self) -> None:
        self._player.set_volume(self.volume)
        self._config.volume = self.volume

    def action_seek_back(self) -> None:
        self._player.seek(-10)

    def action_seek_fwd(self) -> None:
        self._player.seek(10)

    def action_settings(self) -> None:
        def _after(result):
            if result is not None:
                cookies = result.get('cookies', '')
                folder  = result.get('folder', '')
                self._config.cookies_file = cookies
                self._player.cookies_file = cookies
                self._config.local_folder = folder
                msgs = []
                if cookies:
                    msgs.append(f'cookies: {cookies}')
                if folder:
                    msgs.append(f'folder: {folder}')
                self._set_status('Settings saved' + (': ' + ', '.join(msgs) if msgs else ''))

        self.push_screen(
            SettingsScreen(self._config.cookies_file, self._config.local_folder),
            _after,
        )

    def action_quit(self) -> None:
        self._player.quit()
        self.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'source-btn':
            if self.app_mode == 'offline':
                self.action_toggle_mode()
            else:
                self.action_cycle_source()


if __name__ == '__main__':
    app = YTMApp()
    app.run()
