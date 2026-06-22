"""
YouTube Music TUI — main.py
Lightweight terminal YouTube Music / local audio player.

Press ? at any time for the full key list.
"""

import os
import time
import random
import threading

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import (
    Button, DataTable, Header, Input, Label, ListItem, ListView,
    OptionList, Select, Static, TabbedContent, TabPane,
)
from textual.widgets.option_list import Option
from textual.screen import ModalScreen, Screen

import youtube
import player as player_module
import updater
from config import Config, _expand
from library import Library


# ── Helpers ───────────────────────────────────────────────────────────────────

SOURCE_CYCLE = ['ytm', 'yt', 'both']
SOURCE_LABEL = {'ytm': 'YT Music', 'yt': 'YouTube', 'both': 'Both'}

REPEAT_CYCLE = ['off', 'one', 'all']
REPEAT_LABEL = {'off': '🔁 off', 'one': '🔂 one', 'all': '🔁 all'}

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

# Full key reference (shown by the ? screen — the only "help" in the UI).
KEYS_HELP = [
    ('/',        'Search or paste a URL / playlist'),
    ('f / Esc',  'Filter the loaded list / clear filter'),
    ('Enter',    'Play selected track'),
    ('Space',    'Pause / Resume'),
    ('n',        'Next track'),
    ('p',        'Play highlighted track next'),
    ('a',        'Add highlighted track to queue'),
    ('x',        'Stop playback'),
    ('Q',        'Toggle Library / Queue view'),
    ('z',        'Shuffle queue'),
    ('r',        'Cycle repeat (off / one / all)'),
    ('l',        'Like / unlike track'),
    ('w',        'Save current list as a playlist'),
    ('h',        'Home screen'),
    ('t',        'Cycle search source (online)'),
    ('o',        'Toggle online / offline mode'),
    ('c / C',    'Theme picker / cycle theme'),
    ('+ / -',    'Volume up / down'),
    ('← / →',    'Seek -10s / +10s'),
    ('s',        'Settings (cookies + local folder)'),
    ('u',        'Check for updates / update the app'),
    ('?',        'This help'),
    ('q',        'Quit'),
]


def _track_key(t):
    return t.get('id') or t.get('url') or ''


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
    filled = max(0, min(width, filled))
    return '█' * filled + '─' * (width - filled)


def _ago(ts):
    try:
        d = time.time() - float(ts)
    except Exception:
        return ''
    if d < 60:
        return 'just now'
    if d < 3600:
        return f'{int(d // 60)} min ago'
    if d < 86400:
        return f'{int(d // 3600)} h ago'
    return f'{int(d // 86400)} d ago'


# ── Settings screen ───────────────────────────────────────────────────────────

class SettingsScreen(ModalScreen):
    """Modal for cookies file path and local audio folder (with live ✓/✗)."""
    BINDINGS = [Binding('escape', 'dismiss_modal', 'Close')]

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    CSS = """
    SettingsScreen { align: center middle; }
    #settings-box {
        width: 76; height: 18;
        border: round $accent; padding: 1 2; background: $surface;
    }
    #settings-box Label { margin-bottom: 0; }
    #settings-box Input { margin-bottom: 0; }
    .valid { color: $success; height: 1; }
    .invalid { color: $error; height: 1; }
    #btn-row { height: 3; margin-top: 1; }
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
            yield Static('', id='cookies-status', classes='valid')
            yield Label('Local audio folder (offline mode — press o):')
            yield Input(value=self._current_folder, id='folder-input',
                        placeholder=_EG_FOLDER)
            yield Static('', id='folder-status', classes='valid')
            with Horizontal(id='btn-row'):
                yield Button('Save', id='btn-save', variant='primary')
                yield Button('Cancel', id='btn-cancel')

    def on_mount(self) -> None:
        self._validate()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._validate()

    def _validate(self) -> None:
        self._mark('cookies-input', 'cookies-status', want='file')
        self._mark('folder-input', 'folder-status', want='dir')

    def _mark(self, input_id, status_id, want) -> None:
        raw = self.query_one(f'#{input_id}', Input).value.strip()
        st = self.query_one(f'#{status_id}', Static)
        if not raw:
            st.update('')
            return
        path = _expand(raw)
        ok = os.path.isfile(path) if want == 'file' else os.path.isdir(path)
        st.update(('✓ ' if ok else '✗ ') + path)
        st.set_classes('valid' if ok else 'invalid')

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'btn-save':
            cookies = _expand(self.query_one('#cookies-input', Input).value.strip())
            folder  = _expand(self.query_one('#folder-input',  Input).value.strip())
            self.dismiss({'cookies': cookies, 'folder': folder})
        else:
            self.dismiss(None)


# ── Theme picker screen ─────────────────────────────────────────────────────────

class ThemePickerScreen(ModalScreen):
    """Modal listing all built-in themes with live preview on highlight."""
    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]

    CSS = """
    ThemePickerScreen { align: center middle; }
    #theme-box {
        width: 50; height: 24;
        border: round $accent; padding: 1 2; background: $surface;
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

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id:
            self.app.theme = event.option.id

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.app.theme = self._original_theme
        self.dismiss(None)


# ── Keybindings help screen ─────────────────────────────────────────────────────

class KeybindingsScreen(ModalScreen):
    """Read-only list of every key binding."""
    BINDINGS = [
        Binding('escape', 'dismiss_modal', 'Close'),
        Binding('question_mark', 'dismiss_modal', 'Close'),
        Binding('q', 'dismiss_modal', 'Close'),
    ]

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    CSS = """
    KeybindingsScreen { align: center middle; }
    #keys-box {
        width: 64; height: 28;
        border: round $accent; padding: 1 2; background: $surface;
    }
    #keys-title { text-style: bold; margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id='keys-box'):
            yield Label('Keyboard shortcuts  (Esc to close)', id='keys-title')
            lines = '\n'.join(f'  [bold]{k:<9}[/]  {desc}' for k, desc in KEYS_HELP)
            yield Static(lines)


# ── Confirm screen ──────────────────────────────────────────────────────────────

class ConfirmScreen(ModalScreen):
    """Yes / No confirmation modal."""
    BINDINGS = [
        Binding('escape', 'no', 'No'),
        Binding('n', 'no', 'No'),
        Binding('y', 'yes', 'Yes'),
    ]

    CSS = """
    ConfirmScreen { align: center middle; }
    #confirm-box {
        width: 56; height: 9;
        border: round $accent; padding: 1 2; background: $surface;
    }
    #confirm-msg { height: 1fr; }
    #confirm-btns { height: 3; }
    """

    def __init__(self, message):
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id='confirm-box'):
            yield Static(self._message, id='confirm-msg')
            with Horizontal(id='confirm-btns'):
                yield Button('Yes (y)', id='confirm-yes', variant='error')
                yield Button('No (n)', id='confirm-no')

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == 'confirm-yes')

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


# ── Name prompt screen ──────────────────────────────────────────────────────────

class NameScreen(ModalScreen):
    """Prompt for a single text value (playlist name)."""
    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]

    CSS = """
    NameScreen { align: center middle; }
    #name-box {
        width: 60; height: 9;
        border: round $accent; padding: 1 2; background: $surface;
    }
    #name-box Label { margin-bottom: 1; }
    #name-btns { height: 3; margin-top: 1; }
    """

    def __init__(self, prompt, default=''):
        super().__init__()
        self._prompt = prompt
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id='name-box'):
            yield Label(self._prompt)
            yield Input(value=self._default, id='name-input', placeholder='Name…')
            with Horizontal(id='name-btns'):
                yield Button('Save', id='name-save', variant='primary')
                yield Button('Cancel', id='name-cancel')

    def on_mount(self) -> None:
        self.query_one('#name-input', Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'name-save':
            self.dismiss(self.query_one('#name-input', Input).value.strip() or None)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ── Home screen ─────────────────────────────────────────────────────────────────

class HomeScreen(Screen):
    """Boot landing screen: resume sessions + Folders / Liked / Recent."""
    BINDINGS = [
        Binding('escape', 'go_search', 'Search'),
        Binding('slash', 'go_search', 'Search'),
        Binding('q', 'quit_app', 'Quit'),
    ]

    CSS = """
    HomeScreen { align: center middle; }
    #home-box {
        width: 84; height: 32;
        border: round $accent; padding: 1 2; background: $surface;
    }
    #home-title { text-style: bold; color: $accent; margin-bottom: 1; }
    #home-sub { color: $text-muted; margin-bottom: 1; }
    #resume-select { margin-bottom: 1; }
    #home-tabs { height: 1fr; }
    #home-search { margin-top: 1; width: 100%; }
    ListView { height: 1fr; }
    """

    def __init__(self, library):
        super().__init__()
        self._lib = library

    def _track_item(self, track, payload):
        dur = _fmt(track['duration']) if track['duration'] else ''
        label = f"♪ {track['title']}"
        if track.get('uploader'):
            label += f"  —  {track['uploader']}"
        if dur:
            label += f"   {dur}"
        item = ListItem(Label(label))
        item.payload = payload
        return item

    def _empty_item(self):
        item = ListItem(Label('  — empty —'))
        item.payload = None
        return item

    def compose(self) -> ComposeResult:
        with Vertical(id='home-box'):
            yield Label('🎧  YouTube Music TUI', id='home-title')
            yield Label('Pick up where you left off, or browse your library.',
                        id='home-sub')

            sessions = self._lib.sessions()
            opts = []
            for s in sessions:
                title = s.get('title') or 'session'
                n = len(s.get('queue', []))
                opts.append((f"▶ {title}  ·  {n} tracks  ·  {_ago(s.get('ts'))}",
                             s.get('id')))
            yield Select(opts, prompt='Resume a session…', id='resume-select',
                         allow_blank=True)

            with TabbedContent(id='home-tabs'):
                with TabPane('Folders', id='tab-folders'):
                    items = []
                    for p in self._lib.playlists():
                        it = ListItem(Label(f"🎵 {p['name']}  ({len(p['tracks'])})"))
                        it.payload = {'kind': 'playlist', 'name': p['name']}
                        items.append(it)
                    for path in self._lib.folders():
                        it = ListItem(Label(f"📁 {path}"))
                        it.payload = {'kind': 'folder', 'path': path}
                        items.append(it)
                    yield ListView(*(items or [self._empty_item()]), id='list-folders')
                with TabPane('Liked', id='tab-liked'):
                    liked = self._lib.liked()
                    items = [self._track_item(t, {'kind': 'tracklist',
                             'tracks': liked, 'index': i, 'label': 'Liked'})
                             for i, t in enumerate(liked)]
                    yield ListView(*(items or [self._empty_item()]), id='list-liked')
                with TabPane('Recent', id='tab-recent'):
                    recent = self._lib.recent()
                    items = [self._track_item(t, {'kind': 'tracklist',
                             'tracks': recent, 'index': i, 'label': 'Recent'})
                             for i, t in enumerate(recent)]
                    yield ListView(*(items or [self._empty_item()]), id='list-recent')

            yield Button('🔍  Search / Browse', id='home-search', variant='primary')

    def on_mount(self) -> None:
        try:
            self.query_one('#list-folders', ListView).focus()
        except NoMatches:
            pass

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.value is not Select.BLANK and event.value:
            session = self._lib.get_session(event.value)
            if session:
                self.dismiss({'kind': 'resume', 'session': session})

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        payload = getattr(event.item, 'payload', None)
        if payload:
            self.dismiss(payload)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'home-search':
            self.dismiss({'kind': 'search'})

    def action_go_search(self) -> None:
        self.dismiss({'kind': 'search'})

    def action_quit_app(self) -> None:
        self.app.exit()


# ── Main App ──────────────────────────────────────────────────────────────────

class YTMApp(App):
    """YouTube Music TUI."""

    TITLE = 'YouTube Music TUI'

    CSS = """
    Screen { layout: vertical; }

    #search-row { height: 3; padding: 0 1; background: $panel; }
    #search-input { width: 1fr; }
    #source-btn { width: 12; margin-left: 1; }

    #filter-row { height: 3; padding: 0 1; background: $boost; display: none; }
    #filter-row.visible { display: block; }
    #filter-input { width: 1fr; }

    #results-table { height: 1fr; border: none; }

    #player-bar {
        height: 5; padding: 0 2; background: $panel; border-top: solid $accent;
    }
    #now-playing { height: 1; color: $text; text-style: bold; }
    #controls-row { height: 1; color: $text-muted; }
    #progress-row { height: 1; color: $accent; }
    #status-row { height: 1; color: $text-muted; }

    #footer-bar { height: 1; background: $boost; padding: 0 1; }
    #footer-left { width: 1fr; color: $text-muted; }
    #footer-right { width: auto; color: $accent; text-style: bold; }
    """

    BINDINGS = [
        Binding('slash', 'focus_search', 'Search', show=False),
        Binding('f', 'filter', 'Filter', show=False),
        Binding('space', 'toggle_pause', 'Pause', show=False),
        Binding('n', 'next_track', 'Next', show=False),
        Binding('a', 'add_queue', '+Queue', show=False),
        Binding('p', 'play_next', 'Play next', show=False),
        Binding('x', 'stop', 'Stop', show=False),
        Binding('Q', 'toggle_view', 'Queue/Library', show=False),
        Binding('z', 'shuffle', 'Shuffle', show=False),
        Binding('r', 'cycle_repeat', 'Repeat', show=False),
        Binding('l', 'like', 'Like', show=False),
        Binding('w', 'save_playlist', 'Save playlist', show=False),
        Binding('h', 'home', 'Home', show=False),
        Binding('t', 'cycle_source', 'Source', show=False),
        Binding('o', 'toggle_mode', 'Online/Offline', show=False),
        Binding('c', 'theme_picker', 'Theme', show=False),
        Binding('C', 'cycle_theme', 'Cycle theme', show=False),
        Binding('plus,equal', 'vol_up', 'Vol+', show=False),
        Binding('minus', 'vol_down', 'Vol-', show=False),
        Binding('left', 'seek_back', 'Seek-', show=False),
        Binding('right', 'seek_fwd', 'Seek+', show=False),
        Binding('s', 'settings', 'Settings', show=False),
        Binding('u', 'update', 'Update', show=False),
        Binding('escape', 'clear_filter', 'Clear filter', show=False),
        Binding('question_mark', 'show_keys', 'Keys', show=True),
        Binding('q', 'quit', 'Quit', show=False),
    ]

    # Reactive state
    search_source: reactive[str] = reactive('ytm')
    app_mode: reactive[str]      = reactive('online')   # 'online' or 'offline'
    view_mode: reactive[str]     = reactive('library')  # 'library' or 'queue'
    shuffle: reactive[bool]      = reactive(False)
    repeat: reactive[str]        = reactive('off')      # 'off' | 'one' | 'all'
    now_playing: reactive[str]   = reactive('')
    status_msg: reactive[str]    = reactive('Ready — press / to search')
    volume: reactive[int]        = reactive(80)
    # position / duration / is_paused are NOT reactive on purpose: they're polled
    # every second and rendered manually into the player-bar Statics. As reactives
    # they would each trigger a full-screen App repaint per tick — the periodic
    # stutter felt while scrolling. Plain attributes + manual update avoid that.

    def __init__(self):
        super().__init__()
        self._config  = Config()
        self._lib     = Library()
        self._player  = player_module.Player(
            cookies_file=self._config.valid_cookies()
        )
        self._player.set_on_end(self._on_track_end)
        self._results   = []   # list of track dicts from last search/scan
        self._queue     = []   # list of track dicts to play
        self._queue_idx = -1
        self._filter_text = ''
        self._cfg_timer = None
        self._update_available = False   # set by the boot-time update check
        self._restart_requested = False  # set when an update asks for a relaunch
        # Polled playback state (plain attrs — see note on the reactive block).
        self.position = 0.0
        self.duration = 0.0
        self.is_paused = False
        self._last_bar_sig = None        # skip redundant player-bar redraws
        self.search_source = self._config.search_source
        self.volume        = self._config.volume
        self.app_mode      = self._config.app_mode

    # ── Layout ────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id='search-row'):
            yield Input(placeholder='Search or paste URL…', id='search-input')
            yield Button(SOURCE_LABEL[self.search_source], id='source-btn',
                         variant='default')
        with Horizontal(id='filter-row'):
            yield Input(placeholder='Filter loaded list… (Esc to clear)',
                        id='filter-input')
        yield DataTable(id='results-table', cursor_type='row')
        with Vertical(id='player-bar'):
            yield Static('♪  Nothing playing', id='now-playing')
            yield Static('', id='controls-row')
            yield Static('', id='progress-row')
            yield Static(self.status_msg, id='status-row')
        with Horizontal(id='footer-bar'):
            yield Static('', id='footer-left')
            yield Static('? Keys', id='footer-right')

    def on_mount(self) -> None:
        try:
            self.theme = self._config.theme
        except Exception:
            pass
        tbl = self.query_one('#results-table', DataTable)
        tbl.add_column('#',        width=4)
        tbl.add_column('Title',    width=45)
        tbl.add_column('Artist',   width=25)
        tbl.add_column('Duration', width=8)
        self.set_interval(1.0, self._poll_player)
        self._update_mode_ui()
        self._update_footer()
        threading.Thread(target=self._init_player, daemon=True).start()
        threading.Thread(target=self._check_for_update, daemon=True).start()
        # Boot straight into the home screen.
        self.push_screen(HomeScreen(self._lib), self._on_home_result)

    def _init_player(self) -> None:
        if self._player.backend is None:
            self.call_from_thread(
                self._set_status,
                'No audio backend found — install mpv (macOS: brew install mpv) to enable playback.'
            )
            return
        if self._player.backend == 'ffplay':
            self.call_from_thread(
                self._set_status,
                'Using ffplay (limited controls: no seek/volume/position). Install mpv for full control.'
            )
        self._player._ensure_mpv_running()
        self._apply_volume(save=False)

    # ── Self-update ────────────────────────────────────────────────────────

    def _check_for_update(self) -> None:
        """Boot-time, non-blocking: fetch and flag if newer code is available."""
        if not updater.available_backend():
            return
        info = updater.check_for_update()
        if info.get('available'):
            self.call_from_thread(self._on_update_available, info['behind'])

    def _on_update_available(self, behind: int) -> None:
        self._update_available = True
        self._set_status(
            f'Update available — {behind} new commit(s). Press u to update.'
        )
        self._update_footer()

    # ── Home screen result ─────────────────────────────────────────────────

    def _on_home_result(self, result) -> None:
        if not result:
            return
        kind = result.get('kind')
        if kind == 'search':
            self.query_one('#search-input', Input).focus()
        elif kind == 'resume':
            self._resume_session(result['session'])
        elif kind == 'playlist':
            pl = self._lib.get_playlist(result['name'])
            if pl:
                self._populate_results(pl['tracks'])
        elif kind == 'folder':
            self.app_mode = 'offline'
            self._config.app_mode = 'offline'
            self._update_mode_ui()
            self._do_scan_folder(result['path'])
        elif kind == 'tracklist':
            tracks = result['tracks']
            self._populate_results(tracks)
            self._queue = list(tracks)
            self._play_queue_item(result.get('index', 0))

    def _resume_session(self, session) -> None:
        queue = session.get('queue') or []
        if not queue:
            self._set_status('Session had no tracks.')
            return
        self.app_mode = session.get('app_mode', 'online')
        self._config.app_mode = self.app_mode
        self.shuffle = bool(session.get('shuffle', False))
        self.repeat = session.get('repeat', 'off')
        self._update_mode_ui()
        self._populate_results(queue)
        self._queue = list(queue)
        idx = session.get('queue_idx', 0)
        idx = idx if 0 <= idx < len(queue) else 0
        self._play_queue_item(idx, start=float(session.get('position', 0) or 0))
        self._set_status(f'Resumed — {_fmt(session.get("position", 0))} in')

    # ── Search / Scan ─────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == 'filter-input':
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
                    max_results=self._config.max_results,
                )
                self.call_from_thread(self._populate_results, results)
            except Exception as exc:
                self.call_from_thread(self._set_status, f'Search error: {exc}')

        threading.Thread(target=_run, daemon=True).start()

    def _do_load_playlist(self, playlist_id: str) -> None:
        """Load a large playlist: show first page fast (ytmusicapi), then all.
        Falls back to yt-dlp for playlists ytmusicapi can't serve (non-music)."""
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
                if full:
                    # keep_filter so a filter typed during loading survives.
                    self.call_from_thread(self._populate_results, full, True)
                    return
                raise RuntimeError('ytmusicapi returned no tracks')
            except Exception:
                try:
                    url = f'https://www.youtube.com/playlist?list={playlist_id}'
                    opts = youtube._ydl_opts(
                        self._config.valid_cookies(),
                        {'extract_flat': 'in_playlist', 'lazy_playlist': False},
                    )
                    import yt_dlp
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                    results = [
                        youtube._entry_to_dict(e)
                        for e in (info.get('entries') or []) if e
                    ]
                    self.call_from_thread(self._populate_results, results)
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
                if results:
                    self._lib.pin_folder(path)
                else:
                    self.call_from_thread(
                        self._set_status, f'No audio files found in: {path}'
                    )
            except Exception as exc:
                self.call_from_thread(self._set_status, f'Scan error: {exc}')

        threading.Thread(target=_run, daemon=True).start()

    def _populate_results(self, results, keep_filter=False) -> None:
        self._results = results
        if not keep_filter:
            self._filter_text = ''
            try:
                self.query_one('#filter-input', Input).value = ''
            except NoMatches:
                pass
        self.view_mode = 'library'
        self._render_table()
        self._update_footer()
        if not results:
            self._set_status('No results found.')
            return
        mode_label = 'file(s)' if self.app_mode == 'offline' else 'result(s)'
        self._set_status(f'{len(results)} {mode_label} — Enter to play')
        self.query_one('#results-table', DataTable).focus()

    # ── Table rendering ───────────────────────────────────────────────────

    def _accent(self):
        try:
            return self.current_theme.accent or '#89b4fa'
        except Exception:
            return '#89b4fa'

    def _playing_key(self):
        if not self.now_playing:
            return None
        if 0 <= self._queue_idx < len(self._queue):
            return _track_key(self._queue[self._queue_idx])
        return None

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

    def _row_cells(self, marker, title, artist, dur, playing):
        if playing:
            style = f'bold {self._accent()}'
            return [Text(str(marker), style=style), Text(title, style=style),
                    Text(artist, style=style), Text(dur, style=style)]
        return [str(marker), title, artist, dur]

    def _render_table(self) -> None:
        """Render the DataTable for the current view_mode (+ filter in library)."""
        tbl = self.query_one('#results-table', DataTable)
        try:
            saved = tbl.cursor_row
        except Exception:
            saved = 0
        tbl.clear()
        playing_key = self._playing_key()
        count = 0
        if self.view_mode == 'queue':
            for qi, r in enumerate(self._queue):
                playing = (qi == self._queue_idx) and bool(self.now_playing)
                marker = '▶' if playing else str(qi + 1)
                dur = _fmt(r['duration']) if r['duration'] else '?'
                tbl.add_row(*self._row_cells(marker, r['title'], r['uploader'],
                                             dur, playing), key=f'q{qi}')
                count += 1
        else:
            for master_idx, r in self._visible_results():
                playing = playing_key is not None and _track_key(r) == playing_key
                marker = '▶' if playing else str(master_idx + 1)
                dur = _fmt(r['duration']) if r['duration'] else '?'
                tbl.add_row(*self._row_cells(marker, r['title'], r['uploader'],
                                             dur, playing), key=str(master_idx))
                count += 1
        if count:
            tbl.move_cursor(row=min(saved, count - 1))

    def _highlighted_track(self):
        """Return (kind, index, track) for the row under the cursor, or None."""
        tbl = self.query_one('#results-table', DataTable)
        try:
            row = tbl.cursor_row
            key = tbl.coordinate_to_cell_key((row, 0)).row_key.value
        except Exception:
            return None
        if key is None:
            return None
        if self.view_mode == 'queue':
            qi = int(key[1:])
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
            qi = int(key[1:])
            if 0 <= qi < len(self._queue):
                self._play_queue_item(qi)
        else:
            idx = int(key)
            if idx < len(self._results):
                self._queue = self._results[idx:]
                self._queue_idx = 0
                self._play_queue_item(0)

    def _play_queue_item(self, idx: int, start: float = 0.0) -> None:
        if idx < 0 or idx >= len(self._queue):
            return
        track = self._queue[idx]
        self._queue_idx = idx
        self.now_playing = f'{track["title"]}  —  {track["uploader"]}'
        self._lib.add_recent(track)
        self._set_status('Loading…')
        self._render_table()
        self._update_footer()
        url = track['url']

        def _run():
            try:
                self._player.play(url, start=start)
                self.call_from_thread(self._set_status, 'Playing')
            except Exception as exc:
                self.call_from_thread(self._set_status, f'Playback error: {exc}')

        threading.Thread(target=_run, daemon=True).start()

    def _on_track_end(self) -> None:
        """Called by the player when a track finishes (natural eof/error)."""
        if self.repeat == 'one':
            self.call_from_thread(self._play_queue_item, self._queue_idx)
            return
        next_idx = self._queue_idx + 1
        if next_idx < len(self._queue):
            self.call_from_thread(self._play_queue_item, next_idx)
        elif self.repeat == 'all' and self._queue:
            self.call_from_thread(self._play_queue_item, 0)
        else:
            self.call_from_thread(self._set_status, 'Queue finished')
            self.call_from_thread(setattr, self, 'now_playing', '')
            self.call_from_thread(self._render_table)

    # ── Player polling ────────────────────────────────────────────────────

    def _poll_player(self) -> None:
        self.position  = self._player.get_position()
        self.duration  = self._player.get_duration()
        self.is_paused = self._player.is_paused()
        # Only redraw the player bar when something visible actually changed.
        # While paused or idle the position is frozen, so this skips the redraw
        # (and the repaint) entirely — no work happens on most ticks.
        sig = (int(self.position), int(self.duration), self.is_paused,
               self.now_playing, self.volume, self._queue_idx, len(self._queue))
        if sig == self._last_bar_sig:
            return
        self._last_bar_sig = sig
        self._update_player_bar()

    def _update_player_bar(self) -> None:
        pos = self.position
        dur = self.duration
        qpos = (f'{self._queue_idx + 1}/{len(self._queue)}'
                if self._queue and self._queue_idx >= 0 else '0/0')
        pause_icon = '❚❚' if self.is_paused else '▶'
        controls = (f'◀◀  {pause_icon}  ▶▶   Vol: {self.volume}%   '
                    f'Queue {qpos}   {_fmt(pos)} / {_fmt(dur)}')
        bar = _bar(pos, dur, width=50)
        try:
            self.query_one('#now-playing', Static).update(
                f'♪  {self.now_playing}' if self.now_playing else '♪  Nothing playing'
            )
            self.query_one('#controls-row', Static).update(controls)
            self.query_one('#progress-row', Static).update(bar)
        except NoMatches:
            pass

    def _set_status(self, msg: str) -> None:
        self.status_msg = msg
        try:
            self.query_one('#status-row', Static).update(msg)
        except NoMatches:
            pass

    def _update_footer(self) -> None:
        if self.app_mode == 'offline':
            mode, src = '📂 OFFLINE', 'local'
        else:
            mode, src = '🌐 ONLINE', SOURCE_LABEL[self.search_source]
        shuf = '🔀 on' if self.shuffle else '🔀 off'
        rep = REPEAT_LABEL[self.repeat]
        qpos = (f'{self._queue_idx + 1}/{len(self._queue)}'
                if self._queue and self._queue_idx >= 0 else '0/0')
        upd = '    ⬆ update (u)' if self._update_available else ''
        left = (f'{mode} · {src}    {shuf} · {rep}    '
                f'♪ {qpos}    🔊 {self.volume}%    🎨 {self.theme}{upd}')
        try:
            self.query_one('#footer-left', Static).update(left)
        except NoMatches:
            pass

    def _update_mode_ui(self) -> None:
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
        self._update_footer()

    # ── Config flush (debounced) ───────────────────────────────────────────

    def _schedule_config_flush(self) -> None:
        if self._cfg_timer is not None:
            try:
                self._cfg_timer.stop()
            except Exception:
                pass
        self._cfg_timer = self.set_timer(1.0, self._config.flush)

    # ── Actions ───────────────────────────────────────────────────────────

    def action_focus_search(self) -> None:
        self.query_one('#search-input', Input).focus()

    def action_toggle_pause(self) -> None:
        self._player.toggle_pause()
        self.is_paused = self._player.is_paused()
        self._last_bar_sig = None      # force an immediate bar redraw
        self._update_player_bar()

    def action_next_track(self) -> None:
        nxt = self._queue_idx + 1
        if nxt >= len(self._queue):
            if self.repeat == 'all' and self._queue:
                nxt = 0
            else:
                return
        self._play_queue_item(nxt)

    def action_stop(self) -> None:
        self._player.stop()
        self.now_playing = ''
        self._set_status('Stopped')
        self._render_table()
        self._update_footer()

    # ── Queue ─────────────────────────────────────────────────────────────

    def action_add_queue(self) -> None:
        hit = self._highlighted_track()
        if not hit:
            return
        _, _, track = hit
        self._queue.append(track)
        if not self.now_playing:
            self._queue_idx = len(self._queue) - 1
            self._play_queue_item(self._queue_idx)
        else:
            self._set_status(
                f'Added to queue: {track["title"]}  ({len(self._queue)} queued)'
            )
            if self.view_mode == 'queue':
                self._render_table()
        self._update_footer()

    def action_play_next(self) -> None:
        hit = self._highlighted_track()
        if not hit:
            return
        _, _, track = hit
        if not self.now_playing or not self._queue:
            self._queue.append(track)
            self._queue_idx = len(self._queue) - 1
            self._play_queue_item(self._queue_idx)
        else:
            self._queue.insert(self._queue_idx + 1, track)
            self._set_status(f'Plays next: {track["title"]}')
        if self.view_mode == 'queue':
            self._render_table()
        self._update_footer()

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

    def action_shuffle(self) -> None:
        if len(self._queue) <= 1:
            self.shuffle = not self.shuffle
            self._update_footer()
            return
        self.shuffle = True
        cur = None
        if 0 <= self._queue_idx < len(self._queue) and self.now_playing:
            cur = self._queue[self._queue_idx]
        rest = [t for i, t in enumerate(self._queue) if t is not cur]
        random.shuffle(rest)
        if cur is not None:
            self._queue = [cur] + rest
            self._queue_idx = 0
        else:
            self._queue = rest
            self._queue_idx = -1 if not self.now_playing else self._queue_idx
        self._set_status('Queue shuffled')
        if self.view_mode == 'queue':
            self._render_table()
        self._update_footer()

    def action_cycle_repeat(self) -> None:
        i = REPEAT_CYCLE.index(self.repeat)
        self.repeat = REPEAT_CYCLE[(i + 1) % len(REPEAT_CYCLE)]
        self._set_status(f'Repeat: {self.repeat}')
        self._update_footer()

    # ── Library: like / save playlist ──────────────────────────────────────

    def action_like(self) -> None:
        hit = self._highlighted_track()
        track = hit[2] if hit else None
        if track is None and 0 <= self._queue_idx < len(self._queue):
            track = self._queue[self._queue_idx]
        if track is None:
            self._set_status('Nothing to like.')
            return
        now_liked = self._lib.toggle_like(track)
        self._set_status(('♥ Liked: ' if now_liked else '♡ Unliked: ') + track['title'])

    def action_save_playlist(self) -> None:
        if self.view_mode == 'queue':
            tracks = list(self._queue)
        else:
            tracks = [t for _, t in self._visible_results()]
        if not tracks:
            self._set_status('Nothing to save.')
            return

        def _after(name):
            if name:
                self._lib.save_playlist(name, tracks)
                self._set_status(f'Saved playlist "{name}" ({len(tracks)} tracks)')

        self.push_screen(NameScreen('Save current list as playlist:'), _after)

    def action_home(self) -> None:
        self.push_screen(HomeScreen(self._lib), self._on_home_result)

    # ── Themes / mode / source ─────────────────────────────────────────────

    def action_cycle_theme(self) -> None:
        cur = self.theme
        idx = THEME_CYCLE.index(cur) if cur in THEME_CYCLE else -1
        new = THEME_CYCLE[(idx + 1) % len(THEME_CYCLE)]
        self.theme = new
        self._config.update(theme=new)
        self._schedule_config_flush()
        self._set_status(f'Theme: {new}')
        self._update_footer()

    def action_theme_picker(self) -> None:
        names = sorted(self.available_themes.keys())

        def _after(chosen):
            if chosen:
                self.theme = chosen
                self._config.update(theme=chosen)
                self._schedule_config_flush()
                self._set_status(f'Theme: {chosen}')
            self._update_footer()

        self.push_screen(ThemePickerScreen(self.theme, names), _after)

    def action_toggle_mode(self) -> None:
        if self.app_mode == 'online':
            self.app_mode = 'offline'
            self._config.app_mode = 'offline'
            self._update_mode_ui()
            folder = self._config.local_folder
            if folder:
                self._do_scan_folder(folder)
            else:
                self._set_status('Offline mode — press s to set local folder, or type a path and Enter')
                self.query_one('#search-input', Input).focus()
        else:
            self.app_mode = 'online'
            self._config.app_mode = 'online'
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
        self._update_footer()

    def action_vol_up(self) -> None:
        self.volume = min(100, self.volume + 5)
        self._apply_volume()

    def action_vol_down(self) -> None:
        self.volume = max(0, self.volume - 5)
        self._apply_volume()

    def _apply_volume(self, save=True) -> None:
        self._player.set_volume(self.volume)
        if save:
            self._config.update(volume=self.volume)
            self._schedule_config_flush()
        self._update_footer()

    def action_seek_back(self) -> None:
        self._player.seek(-10)

    def action_seek_fwd(self) -> None:
        self._player.seek(10)

    def action_show_keys(self) -> None:
        self.push_screen(KeybindingsScreen())

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

    # ── Self-update action ─────────────────────────────────────────────────

    def action_update(self) -> None:
        if not updater.available_backend():
            self._set_status(
                'Self-update unavailable (not a git checkout) — update with git pull.'
            )
            return
        self._set_status('Checking for updates…')

        def _run():
            info = updater.check_for_update()
            self.call_from_thread(self._after_update_check, info)

        threading.Thread(target=_run, daemon=True).start()

    def _after_update_check(self, info) -> None:
        if info.get('error'):
            self._set_status(f'Update check failed: {info["error"]}')
            return
        if not info.get('available'):
            self._update_available = False
            self._set_status('Already up to date.')
            self._update_footer()
            return

        behind = info['behind']

        def _confirmed(yes):
            if yes:
                self._do_apply_update()
            else:
                self._set_status('Update postponed — press u when ready.')

        self.push_screen(
            ConfirmScreen(
                f'Update available: {behind} new commit(s).\n'
                'Download and install now? (restarts the app)'
            ),
            _confirmed,
        )

    def _do_apply_update(self) -> None:
        self._set_status('Updating… pulling latest code')

        def _run():
            result = updater.apply_update()
            self.call_from_thread(self._after_update_applied, result)

        threading.Thread(target=_run, daemon=True).start()

    def _after_update_applied(self, result) -> None:
        if result.get('error') and not result.get('ok'):
            self._set_status(f'Update failed: {result["error"]}')
            return
        if not result.get('updated'):
            self._update_available = False
            self._set_status('Already up to date.')
            self._update_footer()
            return

        # Updated. If pip failed it's non-fatal but worth surfacing.
        if result.get('error'):
            self._set_status(result['error'])

        def _confirmed(yes):
            if yes:
                self._restart_app()
            else:
                self._set_status(
                    f'{result["message"]} — restart the app to use the new version.'
                )

        self.push_screen(
            ConfirmScreen(
                f'{result["message"]}.\nRestart now to apply the update?'
            ),
            _confirmed,
        )

    def _restart_app(self) -> None:
        """Save state, tear down the player, and ask __main__ to re-exec.

        The actual os.execv happens after app.run() returns so Textual can first
        restore the terminal (exit raw mode / alt screen) — re-exec'ing mid-loop
        would leave the terminal corrupted.
        """
        self._save_session()
        try:
            self._config.flush()
        except Exception:
            pass
        try:
            self._player.quit()
        except Exception:
            pass
        self._restart_requested = True
        self.exit()

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

    # ── Quit ──────────────────────────────────────────────────────────────

    def _save_session(self) -> None:
        if self._queue:
            idx = self._queue_idx if 0 <= self._queue_idx < len(self._queue) else 0
            title = self.now_playing or self._queue[idx].get('title', '')
            self._lib.save_session({
                'title': title,
                'queue': self._queue,
                'queue_idx': idx,
                'position': float(self.position or 0),
                'app_mode': self.app_mode,
                'shuffle': self.shuffle,
                'repeat': self.repeat,
            })

    def _finalize_quit(self) -> None:
        self._save_session()
        try:
            self._config.flush()
        except Exception:
            pass
        self._player.quit()
        self.exit()

    def action_quit(self) -> None:
        if self.now_playing:
            def _after(confirmed):
                if confirmed:
                    self._finalize_quit()
            self.push_screen(
                ConfirmScreen('Something is playing. Quit and save this session?'),
                _after,
            )
        else:
            self._finalize_quit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'source-btn':
            if self.app_mode == 'offline':
                self.action_toggle_mode()
            else:
                self.action_cycle_source()


if __name__ == '__main__':
    app = YTMApp()
    app.run()
    # If an in-app update asked for a relaunch, re-exec now that Textual has
    # restored the terminal so the freshly-pulled code takes effect.
    if getattr(app, '_restart_requested', False):
        updater.restart()
