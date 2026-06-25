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
from textual.coordinate import Coordinate
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import (
    Button, DataTable, Header, Input, Label, ListItem, ListView,
    OptionList, Static, TabbedContent, TabPane,
)
from textual.widgets.option_list import Option
from textual.screen import ModalScreen, Screen
from textual.theme import Theme

import youtube
import player as player_module
import updater
from config import Config, _expand
from library import Library


# ── Helpers ───────────────────────────────────────────────────────────────────

SOURCE_CYCLE = ['ytm', 'yt', 'both']
SOURCE_LABEL = {'ytm': 'YT Music', 'yt': 'YouTube', 'both': 'Both'}

REPEAT_CYCLE = ['off', 'one', 'all']
REPEAT_LABEL = {'off': '↻ off', 'one': '↻ one', 'all': '↻ all'}

# ── Custom themes ─────────────────────────────────────────────────────────────
# Registered at startup via App.register_theme(); they then appear in the picker
# (c) and the quick-cycle (C) alongside Textual's built-ins. Go wild — each is a
# hand-picked palette. The subset listed in ANIMATED_PALETTES below also drives a
# color-wave across the playing track.
CUSTOM_THEMES = [
    Theme(name='synthwave', dark=True, primary='#ff5fd2', secondary='#36f9f6',
          accent='#ff8b39', foreground='#f7f0ff', background='#16111f',
          surface='#241a33', panel='#2f2342', success='#72f1b8',
          warning='#fede5d', error='#fe4450'),
    Theme(name='vaporwave', dark=True, primary='#ff71ce', secondary='#01cdfe',
          accent='#b967ff', foreground='#fdf6ff', background='#1a1426',
          surface='#2a2040', panel='#352a4d', success='#05ffa1',
          warning='#fffb96', error='#ff6e6e'),
    Theme(name='matrix', dark=True, primary='#39ff14', secondary='#00b300',
          accent='#7dff6b', foreground='#c8ffc8', background='#020a02',
          surface='#06160a', panel='#0a2010', success='#39ff14',
          warning='#aaff00', error='#ff3b3b'),
    Theme(name='prism', dark=True, primary='#ff4d4d', secondary='#4dd2ff',
          accent='#ffd24d', foreground='#fafafa', background='#0f0f14',
          surface='#1a1a22', panel='#24242f', success='#4dff88',
          warning='#ffd24d', error='#ff4d6d'),
    Theme(name='ember', dark=True, primary='#ff7b29', secondary='#ffb454',
          accent='#ffd45e', foreground='#fff1e0', background='#170d08',
          surface='#251409', panel='#331c0d', success='#c6d65b',
          warning='#ffb454', error='#ff4d34'),
    Theme(name='deep-ocean', dark=True, primary='#2bd6c6', secondary='#3a8fff',
          accent='#5ef0ff', foreground='#e0f7ff', background='#04121a',
          surface='#082230', panel='#0c3142', success='#3ff0b0',
          warning='#ffd166', error='#ff5d73'),
    Theme(name='blood-moon', dark=True, primary='#ff3b54', secondary='#b3001e',
          accent='#ff7a45', foreground='#ffe6e6', background='#120406',
          surface='#240a0e', panel='#330f15', success='#d6c65b',
          warning='#ff9f45', error='#ff2e4d'),
    Theme(name='aurora', dark=True, primary='#5eead4', secondary='#818cf8',
          accent='#c084fc', foreground='#ecfdf5', background='#06121a',
          surface='#0c2230', panel='#123042', success='#34d399',
          warning='#fbbf24', error='#fb7185'),
    Theme(name='sakura', dark=False, primary='#e35d8f', secondary='#f7a8c4',
          accent='#b56bd6', foreground='#3a2230', background='#fff0f5',
          surface='#ffe1ec', panel='#ffd0e0', success='#5fb98f',
          warning='#e0a23a', error='#e0445d'),
    Theme(name='arctic', dark=False, primary='#2f6fed', secondary='#3aa0ff',
          accent='#00b4d8', foreground='#0d2438', background='#f0f6ff',
          surface='#e0ecfb', panel='#cfe0f5', success='#2faf6f',
          warning='#d99a2b', error='#e0445d'),
    Theme(name='solar-flare', dark=True, primary='#ffb300', secondary='#ff7043',
          accent='#ffd54f', foreground='#fff8e1', background='#1a1205',
          surface='#2a1e08', panel='#3a2a0c', success='#c0ca33',
          warning='#ff7043', error='#e53935'),
    Theme(name='cyberpunk', dark=True, primary='#fcee0a', secondary='#00f0ff',
          accent='#ff2a6d', foreground='#f5fdff', background='#0a0e12',
          surface='#121a22', panel='#1a2630', success='#05ffa1',
          warning='#fcee0a', error='#ff2a6d'),
    Theme(name='mono-amber', dark=True, primary='#ffb000', secondary='#cc8800',
          accent='#ffd166', foreground='#ffcf7a', background='#0c0a06',
          surface='#161208', panel='#1f1a0c', success='#ffb000',
          warning='#ffcf7a', error='#ff5e5e'),
    Theme(name='nebula', dark=True, primary='#a06bff', secondary='#6b8bff',
          accent='#ff6bd6', foreground='#f3eaff', background='#0c0818',
          surface='#171029', panel='#22183b', success='#5fe0c0',
          warning='#ffcf66', error='#ff5d8f'),
]

# Themes whose now-playing track gets an animated color-wave. The value is a list
# of colors the wave interpolates through (2-3 = a cohesive gradient, a long list
# = a rainbow). Only these themes animate; all others use a static accent.
ANIMATED_PALETTES = {
    'synthwave':   ['#ff5fd2', '#b967ff', '#36f9f6', '#b967ff'],
    'vaporwave':   ['#ff71ce', '#b967ff', '#01cdfe', '#05ffa1'],
    'matrix':      ['#0a3d0a', '#39ff14', '#aaff66', '#39ff14'],
    'prism':       ['#ff4d4d', '#ffa64d', '#ffe24d', '#4dff88',
                    '#4dd2ff', '#7d4dff', '#ff4dd2'],
    'ember':       ['#ff3b1f', '#ff7b29', '#ffb454', '#ffd45e'],
    'deep-ocean':  ['#0a3142', '#2bd6c6', '#5ef0ff', '#3a8fff'],
    'blood-moon':  ['#5a0010', '#ff3b54', '#ff7a45', '#ff3b54'],
    'aurora':      ['#34d399', '#5eead4', '#818cf8', '#c084fc'],
    'solar-flare': ['#ff7043', '#ffb300', '#ffd54f', '#fff3c0'],
    'cyberpunk':   ['#ff2a6d', '#fcee0a', '#00f0ff', '#ff2a6d'],
    'nebula':      ['#6b8bff', '#a06bff', '#ff6bd6', '#a06bff'],
}

# Curated "cool" themes for quick-cycle (built-ins + the custom themes above).
THEME_CYCLE = [
    'tokyo-night', 'dracula', 'catppuccin-mocha', 'gruvbox', 'nord',
    'rose-pine', 'monokai', 'flexoki', 'solarized-dark', 'catppuccin-macchiato',
] + [t.name for t in CUSTOM_THEMES]

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
    ('g',        'YouTube account / sign in (For You feed)'),
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


def _hex(c):
    """'#rrggbb' → (r, g, b)."""
    c = c.lstrip('#')
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _wave_text(s, palette, frame, bold=True, spread=0.6, speed=0.45):
    """Build a Rich Text where each character is colored by a moving gradient
    sampled from `palette` (a list of hex colors, treated as a cyclic loop), giving
    a wave that flows across the text as `frame` advances. Cheap: a few float ops
    per character, no allocation beyond the Text itself."""
    if not s:
        return Text('')
    n = len(palette)
    text = Text(s)
    base = 'bold ' if bold else ''
    for i, ch in enumerate(s):
        # Position along the palette loop for this char at this frame.
        p = (i * spread - frame * speed) % n
        fk = int(p)        # floor (p ≥ 0)
        t = p - fk         # fractional part in [0, 1)
        k = fk % n         # guard the float-rounding-to-n edge → always in range
        r1, g1, b1 = _hex(palette[k])
        r2, g2, b2 = _hex(palette[(k + 1) % n])
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        text.stylize(f'{base}#{r:02x}{g:02x}{b:02x}', i, i + 1)
    return text


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
            yield Label('Streaming cookies for age-restricted videos (Netscape .txt):')
            yield Input(value=self._current_cookies, id='cookies-input',
                        placeholder=_EG_COOKIES)
            yield Static('', id='cookies-status', classes='valid')
            yield Static('Optional. For signing in to YouTube Music, use Account '
                         '(g) instead — not this field.', classes='hint')
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
            try:
                self.app._sync_animation()   # live-preview the wave too
            except Exception:
                pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.app.theme = self._original_theme
        self.dismiss(None)
        try:
            self.app._sync_animation()
        except Exception:
            pass


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


# ── Update screen ────────────────────────────────────────────────────────────────

class UpdateScreen(ModalScreen):
    """Update the current branch, or switch between branches (e.g. master / test).

    Dismisses with {'action': 'update'} or {'action': 'switch', 'branch': name},
    or None on cancel.
    """
    BINDINGS = [
        Binding('escape', 'cancel', 'Cancel'),
        Binding('q', 'cancel', 'Cancel'),
    ]

    CSS = """
    UpdateScreen { align: center middle; }
    #update-box {
        width: 60; height: auto;
        border: round $accent; padding: 1 2; background: $surface;
    }
    #update-title { text-style: bold; color: $accent; margin-bottom: 1; }
    #update-info { margin-bottom: 1; }
    #update-box Button { width: 100%; margin-bottom: 1; }
    """

    def __init__(self, branch, revision, branches):
        super().__init__()
        self._branch = branch or '(detached)'
        self._revision = revision or '?'
        # Other branches you can switch to (exclude the current one).
        self._others = [b for b in branches if b and b != branch]

    def compose(self) -> ComposeResult:
        with Vertical(id='update-box'):
            yield Label('Update', id='update-title')
            yield Static(f'Branch: {self._branch}   ({self._revision})',
                         id='update-info')
            yield Button(f'Update this branch ({self._branch})', id='upd-pull',
                         variant='primary')
            # Index-based ids — branch names can contain characters invalid as
            # Textual widget ids (e.g. '/').
            for i, b in enumerate(self._others):
                yield Button(f'Switch to {b}', id=f'upd-switch-{i}')
            yield Button('Cancel (Esc)', id='upd-cancel')

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ''
        if bid == 'upd-pull':
            self.dismiss({'action': 'update'})
        elif bid.startswith('upd-switch-'):
            self.dismiss({'action': 'switch',
                          'branch': self._others[int(bid[len('upd-switch-'):])]})
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ── Account screen ───────────────────────────────────────────────────────────────

class AccountScreen(ModalScreen):
    """YouTube account auth — choose Cookies, OAuth, or Public (none).

    Dismisses with {'method': 'cookies'|'oauth'|'none', 'client_id': str,
    'client_secret': str, 'cookies_file': str}, or None if closed unchanged.
    """
    BINDINGS = [Binding('escape', 'cancel', 'Close')]

    CSS = """
    AccountScreen { align: center middle; }
    #account-box {
        width: 80; height: auto;
        border: round $accent; padding: 1 2; background: $surface;
    }
    #account-title { text-style: bold; color: $accent; }
    #account-box Label { margin-bottom: 0; }
    #account-box Input { margin-bottom: 0; }
    .section { text-style: bold; margin-top: 1; color: $secondary; }
    .hint { color: $text-muted; }
    .valid { color: $success; height: 1; }
    .invalid { color: $error; height: 1; }
    #account-status { height: auto; margin-top: 1; color: $warning; }
    #account-btns { height: 3; margin-top: 1; }
    """

    def __init__(self, method='none', client_id='', client_secret='', cookies_file=''):
        super().__init__()
        self._method = method
        self._client_id = client_id
        self._client_secret = client_secret
        self._cookies_file = cookies_file
        self._cancel = False     # polled by login() to abort
        self._busy = False       # a login/validate thread is running
        self._closed = False     # guards late call_from_thread callbacks

    def compose(self) -> ComposeResult:
        with Vertical(id='account-box'):
            yield Label('YouTube account', id='account-title')
            yield Static(f'Active method: {self._method}', id='account-state')

            yield Label('Cookies  (recommended — works with YT Music)', classes='section')
            yield Input(value=self._cookies_file, id='cookies-input',
                        placeholder=_EG_COOKIES)
            yield Static('', id='cookies-check')
            yield Static('Export cookies.txt from a logged-in music.youtube.com '
                         '(see YOUTUBE_LOGIN.md).', classes='hint')
            yield Button('Use these cookies', id='acct-cookies', variant='primary')

            yield Label('OAuth  (device login)', classes='section')
            yield Input(value=self._client_id, id='cid-input',
                        placeholder='client id .apps.googleusercontent.com')
            yield Input(value=self._client_secret, id='csec-input',
                        password=True, placeholder='client secret')
            yield Static('Note: YouTube Music currently rejects OAuth tokens (HTTP 400) '
                         '— cookies are the working method.', classes='hint')
            yield Button('Log in with OAuth', id='acct-login')

            yield Static('', id='account-status')
            with Horizontal(id='account-btns'):
                yield Button('Use public (no account)', id='acct-none')
                yield Button('Close', id='acct-close')

    def on_mount(self) -> None:
        self._mark_cookies()

    def _status(self, msg) -> None:
        if self._closed:
            return
        try:
            self.query_one('#account-status', Static).update(msg)
        except NoMatches:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == 'cookies-input':
            self._mark_cookies()

    def _mark_cookies(self) -> None:
        raw = self.query_one('#cookies-input', Input).value.strip()
        st = self.query_one('#cookies-check', Static)
        if not raw:
            st.update('')
            return
        path = _expand(raw)
        ok = os.path.isfile(path)
        st.update(('✓ ' if ok else '✗ ') + path)
        st.set_classes('valid' if ok else 'invalid')

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == 'acct-cookies':
            self._use_cookies()
        elif bid == 'acct-login':
            self._start_login()
        elif bid == 'acct-none':
            self._finish('none')
        else:
            self.action_cancel()

    # ── Cookies ──────────────────────────────────────────────────────────
    def _use_cookies(self) -> None:
        if self._busy:
            return
        path = self.query_one('#cookies-input', Input).value.strip()
        if not path:
            self._status('Enter a cookies.txt path first.')
            return
        self._busy = True
        self._status('Checking cookies…')

        def run():
            ok, msg = youtube.cookies_auth_ok(path)
            self.app.call_from_thread(self._after_cookies, ok, msg, path)

        threading.Thread(target=run, daemon=True).start()

    def _after_cookies(self, ok, msg, path) -> None:
        self._busy = False
        if self._closed:
            return
        if ok:
            self._status(f'Signed in as {msg} ✓')
            self._finish('cookies', cookies_file=path, account_name=msg)
        else:
            self._status(f'Cookies not accepted: {msg}')

    # ── OAuth ────────────────────────────────────────────────────────────
    def _start_login(self) -> None:
        if self._busy:
            return
        cid = self.query_one('#cid-input', Input).value.strip()
        csec = self.query_one('#csec-input', Input).value.strip()
        if not cid or not csec:
            self._status('Enter both client ID and client secret first.')
            return
        self._busy = True
        self._cancel = False
        self._status('Requesting device code…')

        def on_code(user_code, url):
            self.app.call_from_thread(
                self._status,
                f'Go to  {url}\nEnter code:  {user_code}\n(waiting for you to authorize…)'
            )

        def run():
            res = youtube.login(cid, csec, on_code,
                                should_cancel=lambda: self._cancel)
            self.app.call_from_thread(self._after_login, res)

        threading.Thread(target=run, daemon=True).start()

    def _after_login(self, res) -> None:
        self._busy = False
        if self._closed:
            return
        if res.get('ok'):
            self._status('Signed in ✓')
            self._finish('oauth')
        else:
            err = res.get('error') or 'login failed'
            self._status('Login cancelled.' if err == 'cancelled'
                         else f'Login failed: {err}')

    # ── Finish / cancel ──────────────────────────────────────────────────
    def _finish(self, method, cookies_file=None, account_name='') -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel = True
        cid = self.query_one('#cid-input', Input).value.strip()
        csec = self.query_one('#csec-input', Input).value.strip()
        cookies = (cookies_file if cookies_file is not None
                   else self.query_one('#cookies-input', Input).value.strip())
        self.dismiss({'method': method, 'client_id': cid,
                      'client_secret': csec, 'cookies_file': cookies,
                      'account_name': account_name})

    def action_cancel(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel = True
        self.dismiss(None)


# ── Home screen ─────────────────────────────────────────────────────────────────

class HomeScreen(Screen):
    """Boot landing screen: resume sessions + Folders / Liked / Recent."""
    BINDINGS = [
        Binding('escape', 'go_search', 'Search'),
        Binding('slash', 'go_search', 'Search'),
        Binding('d', 'delete_item', 'Delete'),
        Binding('r,R', 'rename_item', 'Rename'),
        Binding('q', 'quit_app', 'Quit'),
    ]

    # Active TabPane id → its ListView selector. Only these tabs are manageable
    # (the For-You feed isn't part of the saved library).
    _PANE_LIST = {
        'tab-resume':  '#list-resume',
        'tab-folders': '#list-folders',
        'tab-liked':   '#list-liked',
        'tab-recent':  '#list-recent',
    }

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

    # ── Per-tab item builders (shared by compose() and _reload_tab()) ──────────

    def _resume_items(self):
        items = []
        for s in self._lib.sessions():
            title = s.get('title') or 'session'
            n = len(s.get('queue', []))
            it = ListItem(Label(f"▸ {title}  ·  {n} tracks  ·  {_ago(s.get('ts'))}"))
            it.payload = {'kind': 'session', 'id': s.get('id')}
            items.append(it)
        return items or [self._empty_item()]

    def _folder_items(self):
        items = []
        for p in self._lib.playlists():
            it = ListItem(Label(f"♫ {p['name']}  ({len(p['tracks'])})"))
            it.payload = {'kind': 'playlist', 'name': p['name']}
            items.append(it)
        for path in self._lib.folders():
            it = ListItem(Label(f"▪ {path}"))
            it.payload = {'kind': 'folder', 'path': path}
            items.append(it)
        return items or [self._empty_item()]

    def _liked_items(self):
        liked = self._lib.liked()
        items = [self._track_item(t, {'kind': 'tracklist', 'tracks': liked,
                 'index': i, 'label': 'Liked'}) for i, t in enumerate(liked)]
        return items or [self._empty_item()]

    def _recent_items(self):
        recent = self._lib.recent()
        items = [self._track_item(t, {'kind': 'tracklist', 'tracks': recent,
                 'index': i, 'label': 'Recent'}) for i, t in enumerate(recent)]
        return items or [self._empty_item()]

    def compose(self) -> ComposeResult:
        with Vertical(id='home-box'):
            yield Label('♫  YouTube Music TUI', id='home-title')
            yield Label('Pick up where you left off, or browse your library.   '
                        '·  d delete · r rename', id='home-sub')

            with TabbedContent(id='home-tabs'):
                with TabPane('Resume', id='tab-resume'):
                    yield ListView(*self._resume_items(), id='list-resume')
                with TabPane('For You', id='tab-foryou'):
                    # Populated in the background by on_mount → _populate_foryou.
                    placeholder = ListItem(Label('Loading your feed…'))
                    placeholder.payload = None
                    yield ListView(placeholder, id='list-foryou')
                with TabPane('Folders', id='tab-folders'):
                    yield ListView(*self._folder_items(), id='list-folders')
                with TabPane('Liked', id='tab-liked'):
                    yield ListView(*self._liked_items(), id='list-liked')
                with TabPane('Recent', id='tab-recent'):
                    yield ListView(*self._recent_items(), id='list-recent')

            yield Button('Search / Browse', id='home-search', variant='primary')

    def on_mount(self) -> None:
        try:
            self.query_one('#list-resume', ListView).focus()
        except NoMatches:
            pass
        # Fetch the (personalized when signed in) home feed off the UI thread.
        threading.Thread(target=self._load_foryou, daemon=True).start()

    def _load_foryou(self) -> None:
        err = None
        fallback = False
        try:
            sections = youtube.ytm_home(limit=4)
        except Exception as exc:
            err = f'{type(exc).__name__}: {exc}'
            self._log_feed_error()      # full traceback → err.txt for diagnosis
            sections = []
            # Personalized feed failed — fall back to the generic feed so the tab
            # still shows something instead of going blank.
            if youtube.is_authenticated():
                try:
                    sections = youtube.ytm_home_public(limit=4)
                    fallback = bool(sections)
                except Exception:
                    pass
        try:
            self.app.call_from_thread(self._populate_foryou, sections, err, fallback)
        except Exception:
            pass   # screen dismissed before the feed arrived

    @staticmethod
    def _log_feed_error() -> None:
        """Best-effort: append the active exception's traceback to err.txt."""
        import traceback
        try:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'err.txt')
            with open(path, 'a', encoding='utf-8') as f:
                f.write('\n--- For You feed error ---\n')
                f.write(traceback.format_exc())
        except Exception:
            pass

    def _populate_foryou(self, sections, err=None, fallback=False) -> None:
        try:
            lv = self.query_one('#list-foryou', ListView)
        except NoMatches:
            return
        lv.clear()   # removes only the existing placeholder (captured at call time)
        if not sections:
            msg = (f'Feed error: {err}  —  press g to check sign-in' if err else
                   'No feed yet — press g to sign in for your For You feed.')
            empty = ListItem(Label(msg, markup=False))
            empty.payload = None
            lv.append(empty)
            return
        items = []
        if fallback:
            banner = ListItem(Label(
                f'(personalized feed unavailable: {err}) — showing popular instead',
                markup=False))
            banner.payload = None
            items.append(banner)
        for sec in sections:
            header = ListItem(Label(f"[bold]{sec['title']}[/]"))
            header.payload = None   # non-selectable section heading
            items.append(header)
            songs = [it['track'] for it in sec['items'] if it['kind'] == 'song']
            si = 0
            for it in sec['items']:
                if it['kind'] == 'song':
                    row = self._track_item(it['track'], {
                        'kind': 'tracklist', 'tracks': songs,
                        'index': si, 'label': sec['title']})
                    si += 1
                else:
                    row = ListItem(Label(f"♫ {it['name']}"))
                    row.payload = {'kind': 'foryou_playlist',
                                   'playlistId': it['playlistId']}
                items.append(row)
        lv.extend(items)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        payload = getattr(event.item, 'payload', None)
        if not payload:
            return
        if payload.get('kind') == 'session':
            session = self._lib.get_session(payload.get('id'))
            if session:
                self.dismiss({'kind': 'resume', 'session': session})
            return
        self.dismiss(payload)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'home-search':
            self.dismiss({'kind': 'search'})

    # ── Library management (delete / rename) ───────────────────────────────────

    def _focused_list(self):
        """(pane_id, ListView) for the active tab, or (pane_id, None) if the
        active tab isn't manageable / not found."""
        try:
            pane = self.query_one('#home-tabs', TabbedContent).active
        except NoMatches:
            return None, None
        sel = self._PANE_LIST.get(pane)
        if not sel:
            return pane, None
        try:
            return pane, self.query_one(sel, ListView)
        except NoMatches:
            return pane, None

    def _confirm(self, message, on_yes) -> None:
        def _cb(ok):
            if ok:
                on_yes()
        self.app.push_screen(ConfirmScreen(message), _cb)

    def _reload_tab(self, pane_id) -> None:
        """Rebuild a single tab's ListView from the current library state."""
        builders = {
            'tab-resume':  self._resume_items,
            'tab-folders': self._folder_items,
            'tab-liked':   self._liked_items,
            'tab-recent':  self._recent_items,
        }
        build = builders.get(pane_id)
        sel = self._PANE_LIST.get(pane_id)
        if not build or not sel:
            return
        try:
            lv = self.query_one(sel, ListView)
        except NoMatches:
            return
        lv.clear()
        lv.extend(build())

    def action_delete_item(self) -> None:
        _pane, lv = self._focused_list()
        if lv is None:
            return
        item = lv.highlighted_child
        payload = getattr(item, 'payload', None) if item else None
        if not payload:
            return
        kind = payload.get('kind')
        if kind == 'playlist':
            name = payload['name']
            self._confirm(
                f'Delete playlist "{name}"?',
                lambda: (self._lib.delete_playlist(name),
                         self._reload_tab('tab-folders')))
        elif kind == 'folder':
            path = payload['path']
            self._confirm(
                f'Unpin folder?\n{path}',
                lambda: (self._lib.unpin_folder(path),
                         self._reload_tab('tab-folders')))
        elif kind == 'session':
            sid = payload['id']
            self._confirm(
                'Delete this saved session?',
                lambda: (self._lib.delete_session(sid),
                         self._reload_tab('tab-resume')))
        elif kind == 'tracklist':
            # Liked vs Recent — instant (trivially redone), no confirm.
            tracks = payload.get('tracks') or []
            idx = payload.get('index', -1)
            if not (0 <= idx < len(tracks)):
                return
            track = tracks[idx]
            if payload.get('label') == 'Liked':
                self._lib.toggle_like(track)        # unlike
                self._reload_tab('tab-liked')
            else:
                self._lib.remove_recent(track)
                self._reload_tab('tab-recent')

    def action_rename_item(self) -> None:
        _pane, lv = self._focused_list()
        if lv is None:
            return
        item = lv.highlighted_child
        payload = getattr(item, 'payload', None) if item else None
        if not payload or payload.get('kind') != 'playlist':
            return
        old = payload['name']

        def _cb(new):
            if new and new != old and self._lib.rename_playlist(old, new):
                self._reload_tab('tab-folders')

        self.app.push_screen(
            NameScreen(f'Rename playlist "{old}" to:', default=old), _cb)

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
        Binding('g', 'account', 'Account', show=False),
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
        # One-time migration: earlier builds stored the YTM account cookie dump in
        # `cookies_file`, which is ALSO the yt-dlp/mpv streaming cookie file. An
        # authenticated YouTube session makes yt-dlp get a SABR-only format set it
        # can't play ("Requested format is not available") → every track errors and
        # the queue skips song-by-song with no audio. If the saved streaming cookies
        # are actually a logged-in YTM export, move them to the auth slot and stop
        # feeding them to the player.
        if (not self._config.auth_cookies_file and self._config.valid_cookies()
                and youtube._browser_headers_from_cookies(
                    self._config.valid_cookies()) is not None):
            self._config.auth_cookies_file = self._config.cookies_file
            if self._config.auth_method == 'none':
                self._config.auth_method = 'cookies'
            self._config.cookies_file = ''
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
        # Color-wave animation state (see _sync_animation / _animate_tick).
        self._anim_frame = 0
        self._anim_timer = None          # active Timer while the wave is running
        self._playing_row = None         # displayed row index of the playing track
        self.search_source = self._config.search_source
        self.volume        = self._config.volume
        self.app_mode      = self._config.app_mode
        # Wire the saved auth method (cookies / oauth / none) so ytmusicapi calls
        # run authenticated when configured (personalized search / For You feed).
        youtube.configure_auth(self._config.auth_method,
                               self._config.oauth_client_id,
                               self._config.oauth_client_secret,
                               self._config.auth_cookies_file)

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
        # cursor_foreground_priority='renderable' so the playing row's accent
        # color (set in _row_cells) survives even when it's also the cursor row;
        # the default 'css' lets the cursor style override it (Bug: no highlight).
        yield DataTable(id='results-table', cursor_type='row',
                        cursor_foreground_priority='renderable')
        with Vertical(id='player-bar'):
            yield Static('♪  Nothing playing', id='now-playing')
            yield Static('', id='controls-row')
            yield Static('', id='progress-row')
            yield Static(self.status_msg, id='status-row')
        with Horizontal(id='footer-bar'):
            yield Static('', id='footer-left')
            yield Static('? Keys', id='footer-right')

    def on_mount(self) -> None:
        for t in CUSTOM_THEMES:
            try:
                self.register_theme(t)
            except Exception:
                pass
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
        # If signed in but we don't have the display name yet, fetch it once.
        if youtube.is_authenticated() and not self._config.account_name:
            threading.Thread(target=self._init_account_name, daemon=True).start()
        # Boot straight into the home screen.
        self.push_screen(HomeScreen(self._lib), self._on_home_result)

    def _init_account_name(self) -> None:
        name = youtube.fetch_account_name()
        if name:
            def _save():
                self._config.account_name = name
                self._update_footer()
            try:
                self.call_from_thread(_save)
            except Exception:
                pass

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
        elif kind == 'foryou_playlist':
            self._do_load_playlist(result['playlistId'])

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
            accent = self.current_theme.accent or '#89b4fa'
        except Exception:
            return '#89b4fa'
        # The ANSI themes use Textual's own color names ('ansi_green',
        # 'ansi_bright_magenta') which Rich can't parse — so the styled Text was
        # silently dropped and the playing row showed no highlight. Strip the
        # prefix to Rich's equivalent ('green', 'bright_magenta').
        if isinstance(accent, str) and accent.startswith('ansi_'):
            accent = accent[len('ansi_'):]
        return accent

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
        self._playing_row = None      # recomputed below if the playing track shows
        count = 0
        if self.view_mode == 'queue':
            for qi, r in enumerate(self._queue):
                playing = (qi == self._queue_idx) and bool(self.now_playing)
                marker = '▸' if playing else str(qi + 1)
                dur = _fmt(r['duration']) if r['duration'] else '?'
                tbl.add_row(*self._row_cells(marker, r['title'], r['uploader'],
                                             dur, playing), key=f'q{qi}')
                if playing:
                    self._playing_row = count
                count += 1
        else:
            for master_idx, r in self._visible_results():
                playing = playing_key is not None and _track_key(r) == playing_key
                marker = '▸' if playing else str(master_idx + 1)
                dur = _fmt(r['duration']) if r['duration'] else '?'
                tbl.add_row(*self._row_cells(marker, r['title'], r['uploader'],
                                             dur, playing), key=str(master_idx))
                if playing:
                    self._playing_row = count
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
                # Keep the whole loaded list as the queue and point the index at
                # the chosen track, so jumping behaves like auto-advance — the
                # n/total counter stays stable instead of resetting to 1.
                self._queue = list(self._results)
                self._queue_idx = idx
                self._play_queue_item(idx)

    def _play_queue_item(self, idx: int, start: float = 0.0) -> None:
        if idx < 0 or idx >= len(self._queue):
            return
        track = self._queue[idx]
        self._queue_idx = idx
        self.now_playing = f'{track["title"]}  —  {track["uploader"]}'
        self._lib.add_recent(track)
        self._play_started_at = time.monotonic()   # for the cascade guard below
        self.is_paused = False        # play un-pauses; lets the wave start at once
        self._set_status('Loading…')
        self._render_table()
        self._update_footer()
        self._sync_animation()
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
        # Cascade guard: if tracks keep ending almost immediately after loading,
        # they're failing to play (e.g. extraction error), not finishing. Advancing
        # would skip through the whole queue silently. Stop after a few in a row.
        started = getattr(self, '_play_started_at', None)
        if started is not None and (time.monotonic() - started) < 2.0:
            self._consec_fail = getattr(self, '_consec_fail', 0) + 1
        else:
            self._consec_fail = 0
        if self._consec_fail >= 3:
            self._consec_fail = 0
            self.call_from_thread(
                self._set_status,
                "Playback keeps failing — can't load these tracks (try without "
                "streaming cookies: Settings 's', or check your connection).")
            return
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
        # Start/stop the color-wave to match play/pause/stop state (cheap check).
        self._sync_animation()
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
        pause_icon = '‖' if self.is_paused else '▸'
        controls = (f'◂◂  {pause_icon}  ▸▸   Vol: {self.volume}%   '
                    f'Queue {qpos}   {_fmt(pos)} / {_fmt(dur)}')
        bar = _bar(pos, dur, width=50)
        try:
            # While the wave is running it owns #now-playing — don't clobber it with
            # plain text each poll tick (that would flicker once a second).
            if self._anim_timer is None:
                self.query_one('#now-playing', Static).update(
                    f'♪  {self.now_playing}' if self.now_playing else '♪  Nothing playing'
                )
            self.query_one('#controls-row', Static).update(controls)
            self.query_one('#progress-row', Static).update(bar)
        except NoMatches:
            pass

    # ── Color-wave animation ────────────────────────────────────────────────
    def _sync_animation(self) -> None:
        """Start/stop the color-wave timer to match current state. Safe to call
        often. The wave runs ONLY while an animated theme is active AND a track is
        actively playing (not paused); otherwise the timer is fully stopped, so
        there is zero idle cost when it isn't visible."""
        desired = (self.theme in ANIMATED_PALETTES and bool(self.now_playing)
                   and not self.is_paused)
        if desired and self._anim_timer is None:
            self._anim_timer = self.set_interval(0.08, self._animate_tick)
        elif not desired and self._anim_timer is not None:
            try:
                self._anim_timer.stop()
            except Exception:
                pass
            self._anim_timer = None
            # Repaint once so the last wave frame is replaced by the static accent.
            self._update_player_bar()
            self._render_table()

    def _animate_tick(self) -> None:
        palette = ANIMATED_PALETTES.get(self.theme)
        if not palette or not self.now_playing:
            return
        self._anim_frame += 1
        f = self._anim_frame
        # Now-playing bar (single height-1 widget). Catch everything — a timer
        # callback must never raise (that crashes the app).
        try:
            self.query_one('#now-playing', Static).update(
                Text('♪  ') + _wave_text(self.now_playing, palette, f))
        except Exception:
            pass
        # The playing row's 4 cells (no full-table rebuild). Each column's phase is
        # staggered so the wave appears to travel across the row.
        row = self._playing_row
        if row is None:
            return
        try:
            tbl = self.query_one('#results-table', DataTable)
            values = tbl.get_row_at(row)
        except Exception:
            return
        for col, val in enumerate(values):
            plain = val.plain if isinstance(val, Text) else str(val)
            try:
                tbl.update_cell_at(Coordinate(row, col),
                                   _wave_text(plain, palette, f - col * 4),
                                   update_width=False)
            except Exception:
                pass

    def _set_status(self, msg: str) -> None:
        self.status_msg = msg
        try:
            self.query_one('#status-row', Static).update(msg)
        except NoMatches:
            pass

    def _update_footer(self) -> None:
        if self.app_mode == 'offline':
            mode, src = 'OFFLINE', 'local'
        else:
            mode, src = 'ONLINE', SOURCE_LABEL[self.search_source]
        shuf = '⇄ on' if self.shuffle else '⇄ off'
        rep = REPEAT_LABEL[self.repeat]
        qpos = (f'{self._queue_idx + 1}/{len(self._queue)}'
                if self._queue and self._queue_idx >= 0 else '0/0')
        upd = '    ↑ update (u)' if self._update_available else ''
        base = (f'{mode} · {src}    {shuf} · {rep}    '
                f'♪ {qpos}    vol {self.volume}%    theme {self.theme}')
        # Build as Rich Text so the account name can pop in the theme's accent color
        # against the muted footer. Falls back to the method label when no name yet.
        left = Text(base, no_wrap=True)
        if youtube.is_authenticated():
            name = self._config.account_name or youtube.auth_status()
            left.append('    ')
            left.append(f'♥ {name}', style=f'bold {self._accent()}')
        if upd:
            left.append(upd)
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
        try:
            self.theme = new        # raises if a custom theme failed to register
        except Exception:
            self._set_status(f'Theme unavailable: {new}')
            return
        self._config.update(theme=new)
        self._schedule_config_flush()
        self._set_status(f'Theme: {new}')
        self._update_footer()
        self._sync_animation()      # (de)activate the wave for the new theme

    def action_theme_picker(self) -> None:
        names = sorted(self.available_themes.keys())

        def _after(chosen):
            if chosen:
                self.theme = chosen
                self._config.update(theme=chosen)
                self._schedule_config_flush()
                self._set_status(f'Theme: {chosen}')
            self._update_footer()
            self._sync_animation()

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

    # ── YouTube account ─────────────────────────────────────────────────────

    def action_account(self) -> None:
        def _after(result):
            if result is None:
                return
            method = result.get('method', 'none')
            cid = result.get('client_id', self._config.oauth_client_id)
            csec = result.get('client_secret', self._config.oauth_client_secret)
            cookies = result.get('cookies_file', self._config.auth_cookies_file)
            # Persist the chosen method + its inputs and re-wire the client.
            self._config.auth_method = method
            if cid != self._config.oauth_client_id:
                self._config.oauth_client_id = cid
            if csec != self._config.oauth_client_secret:
                self._config.oauth_client_secret = csec
            # Auth cookies feed ytmusicapi ONLY — deliberately NOT the player. An
            # authenticated YouTube session breaks yt-dlp streaming (SABR-only
            # formats). Streaming cookies are a separate setting (Settings, `s`).
            if cookies != self._config.auth_cookies_file:
                self._config.auth_cookies_file = cookies
            # Persist the signed-in display name for the footer (cleared on sign-out).
            self._config.account_name = (result.get('account_name', '')
                                         if method != 'none' else '')
            youtube.configure_auth(method, cid, csec, cookies)
            self._update_footer()
            self._set_status('YouTube auth: ' + youtube.auth_status()
                             + (' — personalized' if youtube.is_authenticated() else ''))

        self.push_screen(
            AccountScreen(self._config.auth_method,
                          self._config.oauth_client_id,
                          self._config.oauth_client_secret,
                          self._config.auth_cookies_file),
            _after,
        )

    # ── Self-update action ─────────────────────────────────────────────────

    def action_update(self) -> None:
        if not updater.available_backend():
            self._set_status(
                'Self-update unavailable (not a git checkout) — update with git pull.'
            )
            return
        branch = updater.current_branch()
        rev = updater.current_revision()
        branches = updater.list_branches() or ([branch] if branch else [])
        self.push_screen(
            UpdateScreen(branch, rev, branches), self._on_update_choice
        )

    def _on_update_choice(self, choice) -> None:
        if not choice:
            return
        if choice['action'] == 'update':
            self._check_then_update()
        elif choice['action'] == 'switch':
            self._confirm_switch_branch(choice['branch'])

    def _check_then_update(self) -> None:
        self._set_status('Checking for updates…')

        def _run():
            info = updater.check_for_update()
            self.call_from_thread(self._after_update_check, info)

        threading.Thread(target=_run, daemon=True).start()

    def _confirm_switch_branch(self, branch) -> None:
        def _confirmed(yes):
            if yes:
                self._do_switch_branch(branch)
            else:
                self._set_status('Branch switch cancelled.')

        self.push_screen(
            ConfirmScreen(
                f'Switch to branch "{branch}"?\n'
                'This pulls that branch and restarts the app.'
            ),
            _confirmed,
        )

    def _do_switch_branch(self, branch) -> None:
        self._set_status(f'Switching to {branch}…')

        def _run():
            result = updater.switch_branch(branch)
            self.call_from_thread(self._after_branch_switched, result)

        threading.Thread(target=_run, daemon=True).start()

    def _after_branch_switched(self, result) -> None:
        if result.get('error') and not result.get('ok'):
            self._set_status(f'Switch failed: {result["error"]}')
            return
        if result.get('error'):        # non-fatal (e.g. deps) — surface it
            self._set_status(result['error'])
        self._update_available = False
        self._update_footer()

        def _confirmed(yes):
            if yes:
                self._restart_app()
            else:
                self._set_status(
                    f'{result["message"]} — restart to use it.'
                )

        self.push_screen(
            ConfirmScreen(f'{result["message"]}.\nRestart now to load it?'),
            _confirmed,
        )

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
