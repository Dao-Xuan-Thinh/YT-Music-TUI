"""
YouTube Music TUI — main.py
Lightweight terminal YouTube Music player.

Keybindings:
  /         Focus search bar
  Enter     Play selected track
  Space     Pause / Resume
  n         Next in queue
  t         Cycle search source  (YTM → YT → Both)  [online mode only]
  o         Toggle online / offline mode
  + / -     Volume up / down
  ← / →     Seek ±10s
  s         Open settings (cookies file + local audio folder)
  q         Quit
"""

import threading
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label, Static
)
from textual.screen import ModalScreen

import youtube
import player as player_module
from config import Config


# ── Helpers ───────────────────────────────────────────────────────────────────

SOURCE_CYCLE = ['ytm', 'yt', 'both']
SOURCE_LABEL = {'ytm': 'YT Music', 'yt': 'YouTube', 'both': 'Both'}

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
                        placeholder='e.g. C:\\Users\\you\\cookies.txt')
            yield Label('Local audio folder (for offline mode — press o):')
            yield Input(value=self._current_folder, id='folder-input',
                        placeholder='e.g. C:\\Users\\you\\Music')
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
        Binding('space', 'toggle_pause', 'Pause/Resume', show=True),
        Binding('n', 'next_track', 'Next', show=True),
        Binding('t', 'cycle_source', 'Source', show=True),
        Binding('o', 'toggle_mode', 'Online/Offline', show=True),
        Binding('plus,equal', 'vol_up', 'Vol+', show=False),
        Binding('minus', 'vol_down', 'Vol-', show=False),
        Binding('left', 'seek_back', 'Seek-', show=False),
        Binding('right', 'seek_fwd', 'Seek+', show=False),
        Binding('s', 'settings', 'Settings', show=True),
        Binding('q', 'quit', 'Quit', show=True),
    ]

    # Reactive state
    search_source: reactive[str] = reactive('ytm')
    app_mode: reactive[str]      = reactive('online')   # 'online' or 'offline'
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
        yield DataTable(id='results-table', cursor_type='row')
        with Vertical(id='player-bar'):
            yield Static('♪  Nothing playing', id='now-playing')
            yield Static('', id='controls-row')
            yield Static('', id='progress-row')
            yield Static(self.status_msg, id='status-row')
        yield Footer()

    def on_mount(self) -> None:
        tbl = self.query_one('#results-table', DataTable)
        tbl.add_column('#',        width=4)
        tbl.add_column('Title',    width=45)
        tbl.add_column('Artist',   width=25)
        tbl.add_column('Duration', width=8)
        self._poll_timer = self.set_interval(1.0, self._poll_player)
        # Pre-start mpv in background so first play has no startup delay
        threading.Thread(target=self._init_player, daemon=True).start()

    def _init_player(self) -> None:
        self._player._ensure_mpv_running()
        self._apply_volume()

    # ── Search / Scan ─────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
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
        tbl = self.query_one('#results-table', DataTable)
        tbl.clear()
        if not results:
            self._set_status('No results found.')
            return
        for i, r in enumerate(results, 1):
            title  = r['title']
            artist = r['uploader']
            dur    = _fmt(r['duration']) if r['duration'] else '?'
            tbl.add_row(str(i), title, artist, dur, key=str(i - 1))
        mode_label = 'file(s)' if self.app_mode == 'offline' else 'result(s)'
        self._set_status(f'{len(results)} {mode_label} — Enter to play')
        tbl.focus()

    # ── Playback ──────────────────────────────────────────────────────────

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = int(event.row_key.value)
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
