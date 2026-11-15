"""
YouTube Music TUI — main.py
Lightweight terminal YouTube Music / local audio player.

Press ? at any time for the full key list.
"""

import os
import sys
import math
import time
import random
import threading

# First run on a new machine installs whatever requirements.txt is missing, so
# the imports below have something to import (bootstrap.py; --no-bootstrap off).
import bootstrap

bootstrap.ensure()

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Provider
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import (
    Button, DataTable, Input, Label, OptionList, Select, Static,
)
from textual.widgets.option_list import Option
from textual.screen import ModalScreen, Screen
from textual.theme import Theme

from homemap import MapCanvas, HUB

import youtube
import player as player_module
import updater
import mediakeys
import artwork
import stats as stats_module
from config import Config, _expand
from library import Library


# ── Helpers ───────────────────────────────────────────────────────────────────

SOURCE_CYCLE = ['ytm', 'yt', 'both']
SOURCE_LABEL = {'ytm': 'YT Music', 'yt': 'YouTube', 'both': 'Both'}

REPEAT_CYCLE = ['off', 'one', 'all']
REPEAT_LABEL = {'off': '↻ off', 'one': '↻ one', 'all': '↻ all'}

# Cover-art panel geometry (see _sync_art_panel). The table's own columns add up
# to 82 cells, so the panel only appears once the terminal has that much PLUS a
# cover wide enough to be worth looking at — below that the table would start
# losing columns, which is the worse trade.
ART_TABLE_COLS = 86
ART_MIN_COLS = 24
ART_MAX_COLS = 52

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
    Theme(name='paper', dark=False, primary='#8a6d3b', secondary='#6e5f4b',
          accent='#a8927a', foreground='#2b2620', background='#f7f2e7',
          surface='#efe8d6', panel='#e8e0cc', success='#5f8f4f',
          warning='#b3822e', error='#b3452e'),
    Theme(name='mint', dark=False, primary='#14b884', secondary='#38c9a0',
          accent='#0e9c8f', foreground='#10382a', background='#eefaf4',
          surface='#ddf4e9', panel='#cdeede', success='#14b884',
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
    Theme(name='lava-lamp', dark=True, primary='#ff7a3d', secondary='#e0407a',
          accent='#8a2be2', foreground='#ffe9f2', background='#140a1e',
          surface='#1f1029', panel='#2a1533', success='#5fe0c0',
          warning='#ffb03d', error='#ff4d6d'),
    Theme(name='poison', dark=True, primary='#9dfc2e', secondary='#d8ff5e',
          accent='#7a3bff', foreground='#e8ffd6', background='#0a1206',
          surface='#131f0c', panel='#1c2b12', success='#9dfc2e',
          warning='#d8ff5e', error='#c33bff'),
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
    'mono-amber':  ['#ffb000', '#ffcf7a', '#b87700', '#ffcf7a'],
    # Light themes: waves in the theme's saturated range so they read on a light bg.
    'sakura':      ['#e35d8f', '#f7a8c4', '#ffd9e8', '#f7a8c4'],
    'arctic':      ['#2f6fed', '#6fb7ff', '#b8e2ff', '#6fb7ff'],
    'paper':       ['#8a6d3b', '#5c5347', '#a8927a', '#6e5f4b'],
    'mint':        ['#14b884', '#4dd6b0', '#8ce8cd', '#4dd6b0'],
    'lava-lamp':   ['#3d1560', '#8a2be2', '#e0407a', '#ff7a3d',
                    '#ffb03d', '#e0407a', '#8a2be2'],
    'poison':      ['#3f7a0f', '#9dfc2e', '#d8ff5e', '#7a3bff', '#9dfc2e'],
}

# Per-theme Unicode spinner frames for the ♪ slot in the now-playing bar (stepped by the
# same wave timer — a theme animates glyphs only if it's in ANIMATED_PALETTES too). Frames
# within a set must share a display width so the bar doesn't jitter.
ANIMATED_GLYPHS = {
    'synthwave':   ['◢', '◣', '◤', '◥'],
    'vaporwave':   ['◜', '◠', '◝', '◞', '◡', '◟'],
    'matrix':      ['⣾', '⣽', '⣻', '⢿', '⡿', '⣟', '⣯', '⣷'],
    'prism':       ['✦', '✶', '✸', '✹', '✸', '✶'],
    'ember':       ['▁▃▅', '▃▅▇', '▅▇▅', '▇▅▃', '▅▃▁', '▃▁▃'],
    'deep-ocean':  ['◐', '◓', '◑', '◒'],
    'blood-moon':  ['○', '◎', '◉', '●', '◉', '◎'],
    'aurora':      ['✦', '✶', '✸', '✹', '✸', '✶'],
    'sakura':      ['✿', '❀', '✾', '❀'],
    'arctic':      ['❅', '❆', '✻', '❆'],
    'paper':       ['♪', '♫', '♬', '♫'],
    'mint':        ['◐', '◓', '◑', '◒'],
    'solar-flare': ['✦', '✶', '✸', '✹', '✸', '✶'],
    'cyberpunk':   ['⣾', '⣽', '⣻', '⢿', '⡿', '⣟', '⣯', '⣷'],
    'mono-amber':  ['▁▃▅', '▃▅▇', '▅▇▅', '▇▅▃', '▅▃▁', '▃▁▃'],
    'nebula':      ['✦', '✶', '✸', '✹', '✸', '✶'],
    'lava-lamp':   ['◜', '◠', '◝', '◞', '◡', '◟'],
    'poison':      ['⠁', '⠂', '⠄', '⡀', '⢀', '⠠', '⠐', '⠈'],
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
# Grouped so the help screen can render sections. Sections that only apply on a
# particular screen say so in their title — the old flat list mixed them in with
# the global keys, which is half of why it was hard to read.
KEYS_HELP = [
    ('Playback', [
        ('Space',    'Pause / resume'),
        ('n / b',    'Next / previous track (b restarts the song first when mid-play)'),
        ('← / →',    'Seek -10s / +10s'),
        ('+ / -',    'Volume up / down (= works as +)'),
        ('x',        'Stop playback'),
        ('r',        'Cycle repeat: off / one / all'),
        ('z',        'Shuffle the queue'),
        ('R',        'Radio — endless mix from the current track'),
    ]),
    ('Queue', [
        ('Enter',    'Play the highlighted track (the whole list becomes the queue)'),
        ('p',        'Play the highlighted track next'),
        ('a',        'Add the highlighted track to the queue'),
        ('Q',        'Switch between the list and the queue'),
        ('K / J',    'Move the highlighted queue track up / down'),
        ('Shift+↑/↓', 'Same as K / J'),
    ]),
    ('Library', [
        ('l',        'Like / unlike the current track'),
        ('w',        'Save the current list as a playlist'),
        ('A',        'Artist page (for the search box, or the current track)'),
        ('L',        'Lyrics for the current track'),
    ]),
    ('Search & browse', [
        ('/',        'Search, or paste a URL / playlist link'),
        ('Enter',    'In the search pane: play that result now, your list stays'),
        ('a / p',    'In the search pane: add to the queue / play next'),
        ('Tab',      'Jump between the search pane and the list'),
        ('Esc',      'Close the search pane (or clear the filter)'),
        ('f',        'Filter the loaded list'),
        ('t',        'Cycle the search source (YT Music / YouTube / both)'),
        ('o',        'Toggle online / offline mode'),
    ]),
    ('Screens', [
        ('h',        'Home map (and back)'),
        ('Ctrl+p',   'Command palette: every action by name'),
        ('s',        'Listen-stats sync settings (GitHub token + device name)'),
        ('g',        'YouTube account / sign in (unlocks the For You feed)'),
        ('c / C',    'Theme picker / cycle to the next theme'),
        ('u',        'Check for updates and update the app'),
        ('V',        "Changelog — what's new"),
        ('?',        'This help'),
        ('q',        'Quit (when playing: save the session, or just quit; Esc stays)'),
    ]),
    ('On the home map', [
        ('← ↑ ↓ →',  'Move between nodes (and along the history chain)'),
        ('Enter',    'Open a node; on a row: play, load or resume it'),
        ('Enter',    'On a history entry: go back to that list'),
        ('← / Esc',  'Close the open node'),
        ('d',        'Delete the row — unlike, unpin, or drop a playlist or session'),
        ('r',        'Rename the highlighted playlist'),
        ('Esc  h',   'Back to the list'),
        ('/',        'Search'),
    ]),
    ('In the lyrics view (L)', [
        ('t',        'Toggle the translation'),
        ('g',        'Change the translation language'),
        ('Esc q L',  'Close'),
    ]),
    ('In any dialog', [
        ('Esc',      'Close / cancel'),
        ('y / n',    'Answer a yes-no confirmation'),
    ]),
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


def _listened(secs):
    """8040 -> '2h 14m', 840 -> '14m'."""
    m = int(secs // 60)
    h, m = divmod(m, 60)
    return f'{h}h {m:02d}m' if h else f'{m}m'


def _compact(n):
    """4106179 -> '4.1M'."""
    for cut, suffix in ((1_000_000_000, 'B'), (1_000_000, 'M'), (1_000, 'K')):
        if n >= cut:
            v = n / cut
            return f'{v:.1f}{suffix}' if v < 10 else f'{v:.0f}{suffix}'
    return str(n)


def _art_key(track):
    """Identity of a track for cover caching/signatures."""
    if not track:
        return ''
    return track.get('id') or track.get('url') or ''


def _ellipsis(s, width):
    """Trim to `width` CELLS, with a trailing … when something was cut. Cells,
    not characters: a CJK glyph is two cells wide, so a Japanese title that
    passed a len() check still overflowed the panel and wrapped."""
    from rich.cells import cell_len, set_cell_size
    s = s or ''
    if width < 2 or cell_len(s) <= width:
        return s
    return set_cell_size(s, width - 1).rstrip() + '…'


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
    """Modal for cross-device listen-stats sync (GitHub token + device name).

    That's ALL it holds now: streaming cookies moved to Account (g), and the
    offline folder is set by typing its path in the search bar while in
    offline mode (o)."""
    BINDINGS = [Binding('escape', 'dismiss_modal', 'Close')]

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    CSS = """
    SettingsScreen { align: center middle; }
    #settings-box {
        width: 76; height: auto;
        padding: 1 2; background: $panel;
    }
    #settings-title { text-style: bold; color: $accent; margin-bottom: 1; }
    #sync-stats { margin-bottom: 1; }
    #settings-box Label { margin-bottom: 0; }
    #settings-box Input { margin-bottom: 0; }
    .hint { color: $text-muted; }
    #btn-row { height: 3; margin-top: 1; }
    """

    def __init__(self, current_token='', current_device='', stats=None, cfg=None):
        super().__init__()
        self._current_token  = current_token
        self._current_device = current_device
        self._stats = stats
        self._cfg = cfg

    def compose(self) -> ComposeResult:
        with Vertical(id='settings-box'):
            yield Label('Listen-stats sync', id='settings-title')
            if self._stats is not None:
                yield Static(Text(_stats_report(self._stats, self._cfg,
                                                top=False)),
                             id='sync-stats')
            yield Label('GitHub token (classic: gist scope · fine-grained: '
                        'Gists read & write):')
            yield Input(value=self._current_token, id='stats-token-input',
                        password=True, placeholder='ghp_… / github_pat_…')
            yield Static('Paste the same token on every device. Stored locally '
                         'in config.json.', classes='hint')
            yield Label("This device's name in stats:")
            yield Input(value=self._current_device, id='device-name-input')
            with Horizontal(id='btn-row'):
                yield Button('Save', id='btn-save', variant='primary')
                yield Button('Cancel', id='btn-cancel')

    def refresh_stats(self) -> None:
        """Re-render the graph (called by the app when a sync lands)."""
        if self._stats is None:
            return
        try:
            self.query_one('#sync-stats', Static).update(
                Text(_stats_report(self._stats, self._cfg, top=False)))
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'btn-save':
            token  = self.query_one('#stats-token-input', Input).value.strip()
            device = self.query_one('#device-name-input', Input).value.strip()
            self.dismiss({'stats_token': token, 'device_name': device})
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
        padding: 1 2; background: $panel;
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

    # Height is a percentage, not a fixed 28 rows: the old box clipped its last
    # entries with no scrollbar and no hint that anything was below, which read as
    # "keys are missing from the help".
    CSS = """
    KeybindingsScreen { align: center middle; }
    #keys-box {
        width: 78; height: 88%;
        padding: 1 2; background: $panel;
    }
    #keys-title { text-style: bold; }
    #keys-scroll { height: 1fr; scrollbar-size-vertical: 1; }
    #keys-hint { color: $accent; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id='keys-box'):
            yield Label('Keyboard shortcuts', id='keys-title')
            with VerticalScroll(id='keys-scroll'):
                yield Static(self._keys_markup())
            yield Label('↑ ↓ PgUp PgDn scroll   ·   Esc / q / ? close', id='keys-hint')

    # NOT named _render — that shadows a Textual internal and crashes the widget
    # with a null visual (see CLAUDE.md).
    def _keys_markup(self) -> str:
        lines = []
        for section, keys in KEYS_HELP:
            if lines:
                lines.append('')
            lines.append(f'[bold $accent]{section}[/]')
            for key, desc in keys:
                lines.append(f'  [bold]{key:<11}[/] {desc}')
        return '\n'.join(lines)


# ── Changelog ─────────────────────────────────────────────────────────────────
# Curated from the project's git history (newest first). Kept as data (not a
# runtime `git log`) so it works on non-git installs. The mobile app mirrors
# this list so the desktop history is viewable there too.
CHANGELOG = [
    ('1.11', '2026-11-15 15:00', [
        'New look: every part of the app is its own block with a label, no borders; the part that has the focus shows its label in the accent color, and tall terminals get a blank row between blocks',
        'New home: a map. YTTUI in the middle, a node per area (Search, Resume, For You, YT Music, Playlists, Liked, Recent, Stats) — arrows move between nodes, Enter opens a node and lists what is in it underneath',
        'History on the map: every list you open (a playlist, then an album, then a radio) is chained off the node it came from, so h then Enter takes you back to the playlist you left for a radio. Whatever is playing keeps playing',
        'The map background moves with the music (rings of the audio level), and drifts slowly when nothing plays',
        'Search no longer replaces your list: results open in an upper pane with the list kept below. Enter plays a result right away, a / p queue it, Esc or the close button puts the pane away',
        'Columns now fit the window, so a narrow terminal no longer turns the list into a sideways scroller that swallowed the ← → seek keys',
        'The command palette (ctrl+p) lists the app\'s own actions with their keys, instead of Textual\'s defaults',
        'The progress bar spans the whole player block; a top bar shows where you are and the time',
    ]),
    ('1.10.1', '2026-11-15 12:00', [
        'A track whose title holds square brackets no longer crashes the app ("[/x]") or loses the bracketed part ("song [lyrics]") — titles are shown as written everywhere',
        'Volume no longer jumps back to 100% when the audio engine reconnects',
        'Streaming cookies set in Account (g) now apply from the next track, not from the next launch',
        'Playing from a big playlist before it finished loading no longer stops after its first 100 tracks — the queue grows to the whole playlist',
        'A slow search can no longer replace the results of the one you typed after it; the rest of a playlist arriving no longer steals focus or switches the view',
        'Synced lyrics only follow along when they belong to the track that is playing',
        'Album tracks show the album cover; album names now reach the listening stats for every YouTube Music track',
        'Long Japanese / Chinese / Korean titles no longer wrap in the cover panel',
        'The shuffle marker turns off when a new list replaces the shuffled queue, and shuffling keeps a track that is queued twice',
        'Library, settings and stats are written through a temp file, so a kill mid-save can no longer leave them empty',
    ]),
    ('1.10', '2026-10-30 11:35', [
        'Cover art: a wide terminal now shows covers down the right side — the playing track up top, whatever the cursor is on below',
        'Covers are drawn as colored ASCII art; art_style in config.json also takes "braille" (2x4 dots per character, eight times the detail) or "blocks" (half blocks, closer to a photo)',
        'The playing track now lists its album, release year and play count under the cover, plus your own line: how many times you played it and for how long (across every device), with a heart if you liked it',
        'The panel appears only when the results table can keep its full width, and hides itself again when the window shrinks',
        'The cover also reaches the system now-playing panel (Control Center / MPRIS / Windows), which used to show a generic icon',
        'mpv no longer leaves a daemon running after a crash, a kill or an update restart — each launch clears out whatever earlier runs left behind (66 of them had piled up here)',
        'mpv no longer publishes its own "mpv-5555…" entry to the system now-playing list, where it also answered media keys behind the app\'s back',
    ]),
    ('1.9.1', '2026-10-25 10:30', [
        'Unplugging headphones no longer blasts a paused track through the speakers — the system\'s own pause is no longer treated as play/pause',
        'Quitting while playing: "Just quit" now actually quits without saving the session (it used to do nothing); Esc is how you stay',
        'Quitting from the home screen no longer left mpv running in the background',
        'Stats sync: once the shared gist passed 1 MB, GitHub served the last device\'s file cut in half and it was dropped without a word — it is now refetched in full, and an unreadable device is named in the sync status',
        'Stats sync: the library is stored once for all devices instead of a full copy inside every device file — about two thirds off the sync payload',
    ]),
    ('1.9', '2026-10-24 21:40', [
        'Volume: "=" now works as "+" — it never did, despite the help saying so',
        'First launch on a new machine installs its own dependencies; a missing mpv/ffmpeg is reported with the command for your OS',
        'mpv is found even when its installer never put it on PATH (hello, Windows)',
        'Windows: run.cmd creates the venv and picks a modern Python, like run.sh does',
        'Sign-in failures now say what went wrong instead of sitting on "Signing in…"',
    ]),
    ('1.8', '2026-08-14 23:55', [
        'Keyboard help (?) rewritten: grouped into sections and scrollable',
        'It now lists every key — the old one silently cut off the last few and never showed the home-screen, lyrics or dialog keys at all',
    ]),
    ('1.7', '2026-08-14 22:30', [
        'Listening stats expanded: every artist, track and album you have played, all time',
        'Play counts alongside minutes — see most-played, not just most-listened',
        'A weekday × hour heatmap of when you actually listen',
        'Monthly recap: top artist/track, new artists discovered, and how it compares to last month',
        'Existing history is carried over into the new artist/track charts automatically',
    ]),
    ('1.6', '2026-07-21 09:00', [
        'App no longer goes unresponsive after sitting idle — audio self-recovers with no restart',
        'Expanded stats: all-time top artists/tracks, listening streak, this-year total, most-active weekday',
        'This changelog (press V)',
    ]),
    ('1.5', '2026-07-20 14:30', [
        'Gapless auto-advance — the next track is pre-resolved so there is no gap',
        'YT Music tab: your real account playlists + Your Likes on the home screen',
        'Cross-device sync of liked songs, playlists and resume sessions via a private gist',
        'Monthly top charts in the Stats tab',
        'Media keys + OS now-playing panel (macOS / Linux / Windows)',
    ]),
    ('1.4', '2026-07-15 12:13', [
        'Listen-time stats: daily counters + a home Stats tab, synced across devices',
        'Settings (s) is now the sync panel; streaming cookies moved to Account (g)',
    ]),
    ('1.3', '2026-07-13 20:56', [
        'Reorder the queue with K / J (or Shift+↑/↓)',
        'Radio keeps the currently-playing song going instead of restarting it',
        '4 new themes + animated light themes + per-theme glyph spinners; update toast',
        "Fixed silent queue-wide skipping (failure detection uses 'audio never started')",
    ]),
    ('1.2', '2026-07-04 11:33', [
        'Play Music-Premium-only tracks with your signed-in account',
        'Removed the dead OAuth backend (YouTube rejects those tokens)',
        "Fixed songs stuck 'fetching' forever (timeouts + watchdog)",
    ]),
    ('1.1', '2026-07-01 10:05', [
        'Artist pages, radio (endless mix) and synced lyrics with follow + translation',
        'Artist and album rows in search results',
    ]),
    ('1.0', '2026-06-27 10:26', [
        'Durable "Sign in from browser" using live cookies (no more silent expiry)',
        'Fixed the cookie sign-in input freeze; live cookie verification at boot',
    ]),
    ('0.5', '2026-06-26 16:30', [
        'Anti-hang pass: serialized ytmusicapi with per-request timeouts',
        'Fixed the mpv --no-terminal input freeze; added a freeze watchdog',
    ]),
    ('0.4', '2026-06-25 15:11', [
        'Home-screen library management (delete / rename) + a Resume tab',
    ]),
    ('0.3', '2026-06-24 12:48', [
        'Sign in to YouTube + a personalized For You feed',
        '14 custom themes with the animated color-wave; cookie/browser auth',
    ]),
    ('0.2', '2026-06-22 14:44', [
        'Home screen, library/sessions, shuffle/repeat, resume',
        'In-app self-update via git (u); monochrome glyphs; scroll-stutter fix',
    ]),
    ('0.1', '2026-06-21 19:39', [
        'Baseline TUI: YouTube Music via ytmusicapi (full playlists + artists)',
        'Queue, in-list filter, theme switching; per-process mpv IPC',
        'Cross-platform mpv IPC (macOS / Linux / Windows)',
    ]),
]


class ChangelogScreen(ModalScreen):
    """Read-only version history of the desktop app."""
    BINDINGS = [
        Binding('escape', 'dismiss_modal', 'Close'),
        Binding('q', 'dismiss_modal', 'Close'),
        Binding('V', 'dismiss_modal', 'Close'),
    ]

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    CSS = """
    ChangelogScreen { align: center middle; }
    #changelog-box {
        width: 76; height: 30;
        padding: 1 2; background: $panel;
    }
    #changelog-title { text-style: bold; color: $accent; margin-bottom: 1; }
    #changelog-scroll { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        rev = ''
        try:
            rev = updater.current_revision() or ''
        except Exception:
            pass
        with Vertical(id='changelog-box'):
            yield Label(f'Changelog{("  ·  " + rev) if rev else ""}   (Esc to close)',
                        id='changelog-title')
            lines = []
            for version, date, notes in CHANGELOG:
                lines.append(f'[bold]v{version}[/]   [dim]{date}[/]')
                for n in notes:
                    lines.append(f'  · {n}')
                lines.append('')
            with VerticalScroll(id='changelog-scroll'):
                yield Static(Text.from_markup('\n'.join(lines)))


# ── Lyrics screen ─────────────────────────────────────────────────────────────

class LyricsScreen(ModalScreen):
    """Lyrics for the current track. Follows playback (highlights the current line +
    auto-scrolls) when the song has synced lyrics; 't' toggles an English (or chosen-language)
    translation under each line; 'g' changes the target language."""
    BINDINGS = [
        Binding('escape', 'dismiss_modal', 'Close'),
        Binding('q', 'dismiss_modal', 'Close'),
        Binding('L', 'dismiss_modal', 'Close'),
        Binding('t', 'toggle_translate', 'Translate'),
        Binding('g', 'change_lang', 'Language'),
    ]

    CSS = """
    LyricsScreen { align: center middle; }
    #lyrics-box {
        width: 76; height: 32;
        padding: 1 2; background: $panel;
    }
    #lyrics-title { text-style: bold; }
    #lyrics-hint { color: $text-muted; margin-bottom: 1; }
    #lyrics-scroll { height: 1fr; }
    """

    def __init__(self, title, data, video_id):
        super().__init__()
        self._title = title
        self._data = data            # {'synced','lines','text','source'}
        self._vid = video_id
        self._lines = data.get('lines') or []
        self._synced = bool(data.get('synced'))
        self._translated = None      # list[str] aligned to lines, or None
        self._show_trans = False
        self._lang = 'en'
        self._cur = -1

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def compose(self) -> ComposeResult:
        from textual.containers import VerticalScroll
        with Vertical(id='lyrics-box'):
            yield Label(f'♪ {self._title}', id='lyrics-title', markup=False)
            yield Label(' ', id='lyrics-hint')
            with VerticalScroll(id='lyrics-scroll'):
                yield Static('…', id='lyrics-body')

    def on_mount(self) -> None:
        self._update_hint()
        self._refresh_lyrics()
        if self._synced:
            self.set_interval(0.25, self._tick)

    def _update_hint(self) -> None:
        src = self._data.get('source') or ''
        bits = []
        if self._synced:
            bits.append('following')
        bits.append(f't: translate ({self._lang}) {"on" if self._show_trans else "off"}')
        bits.append('g: language')
        hint = '  ·  '.join(bits)
        try:
            self.query_one('#lyrics-hint', Label).update(f'{src}   {hint}' if src else hint)
        except NoMatches:
            pass

    def _current_index(self) -> int:
        if not self._synced:
            return -1
        # The position belongs to whatever is PLAYING. These lyrics may be for
        # the highlighted row instead, or the queue may have moved on since —
        # following along with another song's clock lights up the wrong lines.
        app = self.app
        q, qi = getattr(app, '_queue', []), getattr(app, '_queue_idx', -1)
        playing = q[qi].get('id') if 0 <= qi < len(q) and app.now_playing else None
        if playing != self._vid:
            return -1
        pos_ms = getattr(self.app, 'position', 0.0) * 1000
        cur = -1
        for i, ln in enumerate(self._lines):
            if ln['start'] <= pos_ms:
                cur = i
            else:
                break
        return cur

    def _refresh_lyrics(self) -> None:
        from rich.text import Text
        try:
            body = self.query_one('#lyrics-body', Static)
        except NoMatches:
            return
        if not self._lines:
            body.update('(no lyrics)')
            return
        # Build a Rich Text (styled per line) rather than a markup string, so lyric text
        # containing '[' can never break parsing. The current line is bold + the theme accent
        # (like mobile); already-sung lines dim; upcoming lines normal.
        accent = self.app._accent()
        t = Text()
        for i, ln in enumerate(self._lines):
            text = ln['text'] or ' '
            current = self._synced and i == self._cur
            if current:
                t.append('▸ ' + text + '\n', style=f'bold {accent}')
            elif self._synced and i < self._cur:
                t.append(text + '\n', style='dim')
            else:
                t.append(text + '\n')
            if self._show_trans and self._translated and i < len(self._translated):
                tr = self._translated[i]
                if tr and tr != text:
                    # Keep the current line's translation readable; dim the rest.
                    t.append('   ' + tr + '\n', style='italic' if current else 'dim italic')
        body.update(t)

    def _tick(self) -> None:
        cur = self._current_index()
        if cur != self._cur:
            self._cur = cur
            self._refresh_lyrics()
            self._scroll_to_current()

    def _scroll_to_current(self) -> None:
        if self._cur < 0:
            return
        # Approximate display row: each earlier line is 1 row, +1 if it has a shown
        # translation.
        row = 0
        for i in range(self._cur):
            row += 1
            if self._show_trans and self._translated and i < len(self._translated):
                tr = self._translated[i]
                if tr and tr != (self._lines[i]['text'] or ' '):
                    row += 1
        try:
            scroll = self.query_one('#lyrics-scroll')
            # Center the current line in the viewport and glide to it (smooth follow).
            visible = scroll.size.height or 20
            scroll.scroll_to(y=max(0, row - visible // 2), animate=True, duration=0.45)
        except NoMatches:
            pass

    def action_toggle_translate(self) -> None:
        self._show_trans = not self._show_trans
        self._update_hint()
        if self._show_trans and self._translated is None:
            self._fetch_translation()
        else:
            self._refresh_lyrics()

    def action_change_lang(self) -> None:
        def _after(code):
            if code:
                self._lang = code.strip().lower()
                self._translated = None
                self._update_hint()
                if self._show_trans:
                    self._fetch_translation()
        self.app.push_screen(
            NameScreen('Translate to (language code, e.g. en, vi, ja):', self._lang), _after)

    def _fetch_translation(self) -> None:
        try:
            self.query_one('#lyrics-hint', Label).update('[dim]translating…[/]')
        except NoMatches:
            pass
        text = self._data.get('text') or ''
        lang = self._lang

        def _run():
            translated = youtube.translate_text(text, lang)
            lines = translated.split('\n') if translated else []
            self.app.call_from_thread(self._apply_translation, lines)

        threading.Thread(target=_run, daemon=True).start()

    def _apply_translation(self, lines) -> None:
        self._translated = lines
        self._update_hint()
        self._refresh_lyrics()


# ── Artist screen ─────────────────────────────────────────────────────────────

class ArtistScreen(ModalScreen):
    """An artist page: header + sections (songs / albums / singles / videos). Selecting a
    song dismisses with ('play', section_tracks, index); an album with ('album', browseId,
    name). The app acts on the result."""
    BINDINGS = [
        Binding('escape', 'cancel', 'Close'),
        Binding('q', 'cancel', 'Close'),
    ]

    CSS = """
    ArtistScreen { align: center middle; }
    #artist-box {
        width: 84; height: 34;
        padding: 1 2; background: $panel;
    }
    #artist-title { text-style: bold; }
    #artist-sub { color: $text-muted; margin-bottom: 1; }
    #artist-table { height: 1fr; }
    """

    def __init__(self, page):
        super().__init__()
        self._page = page
        # Flat row model: list of (kind, payload) parallel to the table rows.
        # kind 'song' → (tracks_list, index); kind 'album' → item dict; 'header' → None.
        self._rows = []

    def action_cancel(self) -> None:
        self.dismiss(None)

    def compose(self) -> ComposeResult:
        with Vertical(id='artist-box'):
            yield Label(self._page.get('name') or 'Artist', id='artist-title',
                        markup=False)
            subs = self._page.get('subscribers') or ''
            yield Label(f'{subs} subscribers' if subs else ' ', id='artist-sub')
            yield DataTable(id='artist-table', cursor_type='row', zebra_stripes=True)

    def on_mount(self) -> None:
        tbl = self.query_one('#artist-table', DataTable)
        tbl.add_columns(' ', 'Title', 'Info')
        for sec in self._page.get('sections') or []:
            items = sec.get('items') or []
            # Section header row (non-selectable).
            self._rows.append(('header', None))
            tbl.add_row(Text(f'— {sec["title"]} —', style='bold'), '', '',
                        key=f'h{len(self._rows)}')
            songs = [it for it in items if not (isinstance(it, dict) and it.get('kind') == 'album')]
            for it in items:
                if isinstance(it, dict) and it.get('kind') == 'album':
                    self._rows.append(('album', it))
                    yr = it.get('year') or ''
                    tbl.add_row('◇', Text(it.get('name') or ''), Text(str(yr)),
                                key=f'r{len(self._rows)}')
                else:
                    idx = songs.index(it)
                    self._rows.append(('song', (songs, idx)))
                    dur = _fmt(it.get('duration')) if it.get('duration') else ''
                    tbl.add_row('♪', Text(it.get('title') or ''), dur,
                                key=f'r{len(self._rows)}')
        tbl.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()   # don't let it bubble to the app's results-table handler
        key = event.row_key.value
        if not key or key.startswith('h'):
            return
        i = int(key[1:]) - 1
        if not (0 <= i < len(self._rows)):
            return
        kind, payload = self._rows[i]
        if kind == 'song':
            tracks, idx = payload
            self.dismiss(('play', tracks, idx,
                          self._page.get('name') or 'Artist'))
        elif kind == 'album':
            self.dismiss(('album', payload.get('browseId'), payload.get('name') or 'Album'))


# ── Confirm screen ──────────────────────────────────────────────────────────────

class ConfirmScreen(ModalScreen):
    """Yes / No confirmation modal.

    Default: No and Esc are the same thing — "never mind" — and dismiss False.
    With cancel=True the dialog is three-way and dismisses True / False / None,
    so No can be a real second action (quit WITHOUT saving) while Esc stays the
    way out. Callers that only test truthiness are unaffected: None is falsy.
    """
    BINDINGS = [
        Binding('escape', 'cancel', 'Cancel'),
        Binding('n', 'no', 'No'),
        Binding('y', 'yes', 'Yes'),
    ]

    CSS = """
    ConfirmScreen { align: center middle; }
    #confirm-box {
        width: 56; height: auto;      /* grows with the message (3-line quit) */
        padding: 1 2; background: $panel;
    }
    #confirm-msg { height: auto; margin-bottom: 1; }
    #confirm-btns { height: 3; }
    """

    def __init__(self, message, yes_label='Yes (y)', no_label='No (n)',
                 cancel=False):
        super().__init__()
        self._message = message
        self._yes_label = yes_label
        self._no_label = no_label
        self._cancel = cancel

    def compose(self) -> ComposeResult:
        with Vertical(id='confirm-box'):
            yield Static(self._message, id='confirm-msg', markup=False)
            with Horizontal(id='confirm-btns'):
                yield Button(self._yes_label, id='confirm-yes', variant='error')
                yield Button(self._no_label, id='confirm-no')

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == 'confirm-yes')

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(None if self._cancel else False)


# ── Name prompt screen ──────────────────────────────────────────────────────────

class NameScreen(ModalScreen):
    """Prompt for a single text value (playlist name)."""
    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]

    CSS = """
    NameScreen { align: center middle; }
    #name-box {
        width: 60; height: 9;
        padding: 1 2; background: $panel;
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
            yield Label(self._prompt, markup=False)
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
        padding: 1 2; background: $panel;
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
    """YouTube account auth — choose Browser, Cookies, or Public (none).

    Dismisses with {'method': 'browser'|'cookies'|'none', 'cookies_file': str,
    'account_name': str, 'browser': str, 'profile': str}, or None if closed
    unchanged. (OAuth was removed — YouTube rejects those tokens with HTTP 400.)
    """
    BINDINGS = [Binding('escape', 'cancel', 'Close')]

    CSS = """
    AccountScreen { align: center middle; }
    #account-box {
        width: 80; height: auto;
        padding: 1 2; background: $panel;
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

    def __init__(self, method='none', cookies_file='', browser='', profile='',
                 stream_cookies='', on_stream_cookies=None):
        super().__init__()
        self._method = method
        self._cookies_file = cookies_file
        self._browser = browser
        self._profile = profile
        self._profiles = youtube.detect_browser_profiles()
        self._closed = False     # guards late call_from_thread callbacks
        # Streaming cookies (age-restricted playback) live here too since this
        # is the cookies screen — but they feed the PLAYER only, never the
        # account auth. Applied immediately via the callback (valid path or
        # cleared), so no Save button / dismiss plumbing is needed.
        self._stream_cookies = stream_cookies
        self._on_stream_cookies = on_stream_cookies

    def compose(self) -> ComposeResult:
        with Vertical(id='account-box'):
            yield Label('YouTube account', id='account-title')
            yield Static(f'Active method: {self._method}', id='account-state')

            yield Label('Browser  (recommended — durable, re-reads each launch)',
                        classes='section')
            options = [(p['label'], f"{p['browser']}\x00{p['profile']}")
                       for p in self._profiles]
            # Pre-select the saved browser/profile if it's still present; otherwise
            # leave it blank (don't pass a value — the no-selection sentinel differs
            # across Textual versions, so let the constructor default to it).
            sel_kwargs = {}
            if self._browser:
                want = f'{self._browser}\x00{self._profile}'
                if any(v == want for _, v in options):
                    sel_kwargs['value'] = want
            yield Select(options, id='browser-select',
                         prompt='Pick a browser profile…', allow_blank=True,
                         **sel_kwargs)
            yield Static('Reads your live music.youtube.com session straight from the '
                         "browser — never expires while you're logged in. Firefox-family "
                         '(incl. Zen) works; Chrome/Edge are blocked by App-Bound '
                         'Encryption on Windows.', classes='hint')
            yield Button('Sign in from browser', id='acct-browser', variant='primary')

            yield Label('Cookies  (manual export — expires, re-export to renew)',
                        classes='section')
            yield Input(value=self._cookies_file, id='cookies-input',
                        placeholder=_EG_COOKIES)
            yield Static('', id='cookies-check', markup=False)
            yield Static('Export cookies.txt from a logged-in music.youtube.com '
                         '(see YOUTUBE_LOGIN.md).', classes='hint')
            yield Button('Use these cookies', id='acct-cookies')

            yield Static('OAuth sign-in was removed — YouTube rejects those tokens '
                         '(HTTP 400). Use Browser or Cookies above.', classes='hint')

            yield Label('Streaming cookies  (optional — age-restricted playback only)',
                        classes='section')
            yield Input(value=self._stream_cookies, id='stream-cookies-input',
                        placeholder=_EG_COOKIES)
            yield Static('', id='stream-cookies-check', markup=False)
            yield Static('Fed to mpv/yt-dlp for playback only — NOT your sign-in '
                         '(signed-in streaming cookies actually break playback). '
                         'Applies as soon as the path is valid; clear to remove.',
                         classes='hint')

            yield Static('', id='account-status', markup=False)
            with Horizontal(id='account-btns'):
                yield Button('Use public (no account)', id='acct-none')
                yield Button('Close', id='acct-close')

    def on_mount(self) -> None:
        self._mark_cookies()
        self._mark_stream_cookies(apply=False)

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
        elif event.input.id == 'stream-cookies-input':
            self._mark_stream_cookies()

    def _mark_stream_cookies(self, apply=True) -> None:
        """Live ✓/✗ for the streaming-cookies path; apply it (or a clear) as
        soon as the value is definitive — no Save button."""
        raw = self.query_one('#stream-cookies-input', Input).value.strip()
        st = self.query_one('#stream-cookies-check', Static)
        if not raw:
            st.update('')
            if apply and self._on_stream_cookies:
                self._on_stream_cookies('')
            return
        path = _expand(raw)
        ok = os.path.isfile(path)
        st.update(('✓ ' if ok else '✗ ') + path)
        st.set_classes('valid' if ok else 'invalid')
        if apply and ok and self._on_stream_cookies:
            self._on_stream_cookies(path)

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
        if bid == 'acct-browser':
            self._use_browser()
        elif bid == 'acct-cookies':
            self._use_cookies()
        elif bid == 'acct-none':
            self._finish('none')
        else:
            self.action_cancel()

    # ── Browser (live cookies) ───────────────────────────────────────────
    def _use_browser(self) -> None:
        # UI thread (button press). Just record the chosen browser/profile and
        # dismiss here — the live extraction + auth check runs in the background
        # afterwards (action_account._after → _verify_account), so a slow/locked
        # cookie store never blocks the UI and the modal never dismisses from a
        # worker thread (CLAUDE.md gotcha).
        # Valid option values are "browser\x00profile" strings; the no-selection
        # sentinel is a non-str (varies by Textual version) — treat it as "nothing
        # picked" without referencing the sentinel.
        sel = self.query_one('#browser-select', Select).value
        if not isinstance(sel, str) or '\x00' not in sel:
            self._status('Pick a browser profile first.')
            return
        browser, _, profile = sel.partition('\x00')
        self._finish('browser', browser=browser, profile=profile)

    # ── Cookies ──────────────────────────────────────────────────────────
    def _use_cookies(self) -> None:
        # Runs on the UI thread (button press). Do only a fast LOCAL sanity check
        # here, then dismiss on the UI thread — NEVER validate-then-dismiss from a
        # worker thread (that wedges Textual's input driver; see the CLAUDE.md
        # gotcha). The live session check happens in the background afterwards
        # (action_account._after → _verify_account), exactly like boot.
        path = self.query_one('#cookies-input', Input).value.strip()
        if not path:
            self._status('Enter a cookies.txt path first.')
            return
        if not os.path.exists(path):
            self._status('No file at that path.')
            return
        if youtube._browser_headers_from_cookies(path) is None:
            self._status("That file isn't a logged-in music.youtube.com export — "
                         're-export with login cookies.')
            return
        self._finish('cookies', cookies_file=path, account_name='')

    # ── Finish / cancel ──────────────────────────────────────────────────
    def _finish(self, method, cookies_file=None, account_name='',
                browser='', profile='') -> None:
        if self._closed:
            return
        self._closed = True
        cookies = (cookies_file if cookies_file is not None
                   else self.query_one('#cookies-input', Input).value.strip())
        self.dismiss({'method': method, 'cookies_file': cookies,
                      'account_name': account_name,
                      'browser': browser, 'profile': profile})

    def action_cancel(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.dismiss(None)


# ── Home screen ─────────────────────────────────────────────────────────────────

def _stats_report(stats, cfg, width=34, top=True):
    """Multi-line plain-text listen-time report: 7-day bar graph, totals,
    per-device split, monthly top charts (top=False skips them — the sync
    panel stays compact), sync status. Shared by the home Stats tab and the
    sync panel (s)."""
    dev_id = cfg.stats_device_id if cfg else ''
    dev_name = (cfg.stats_device_name if cfg else '') or 'this device'
    days = stats.merged_days(7, own_device_id=dev_id)
    totals = stats.totals(own_device_id=dev_id)
    fmt = stats_module.fmt_mins
    peak = max((s for _, s in days), default=0.0)
    lines = ['Listening time — last 7 days', '']
    for i, (day, secs) in enumerate(days):
        if i == len(days) - 1:
            label = 'Today    '
        else:
            label = time.strftime('%a %m-%d', time.strptime(day, '%Y-%m-%d'))
        filled = int(round(width * secs / peak)) if peak > 0 else 0
        bar = '█' * filled + '░' * (width - filled)
        lines.append(f'{label}  {bar}  {fmt(secs)}')
    lines.append('')
    lines.append(f'Today {fmt(totals["today"])}   ·   '
                 f'7 days {fmt(totals["week"])}   ·   '
                 f'All time {fmt(totals["all"])}')
    devices = stats.per_device(own_device_id=dev_id, own_device_name=dev_name)
    if devices:
        lines.append('  ·  '.join(f'{name} {fmt(total)}'
                                  for name, total in devices))
    if top:
        # Extras: streak / this-year / biggest day / most-active weekday.
        cur_streak, best_streak = stats.streak(own_device_id=dev_id)
        bd_day, bd_secs = stats.best_day(own_device_id=dev_id)
        yr = stats.year_total(own_device_id=dev_id)
        wk = stats.weekday_totals(own_device_id=dev_id)
        extras = []
        if cur_streak:
            extras.append(f'Streak {cur_streak}d (best {best_streak})')
        if yr:
            extras.append(f'This year {fmt(yr)}')
        if bd_secs:
            extras.append(f'Biggest day {bd_day} {fmt(bd_secs)}')
        if any(wk):
            extras.append('Most active ' +
                          stats_module.WEEKDAY_NAMES[max(range(7), key=lambda i: wk[i])])
        if extras:
            lines.append('')
            lines.append('  ·  '.join(extras))
        # Top charts, this month AND all time (the tab scrolls).
        for scope, heading in (('month', 'Top this month'), ('all', 'Top all time')):
            t_artists = stats.top_artists(5, own_device_id=dev_id, scope=scope)
            t_tracks = stats.top_tracks(5, own_device_id=dev_id, scope=scope)
            if not (t_artists or t_tracks):
                continue
            lines.append('')
            lines.append(heading)
            for i, (artist, secs) in enumerate(t_artists, 1):
                lines.append(f'  {i}. {artist[:34]:<34}  {fmt(secs)}')
            if t_tracks:
                lines.append('')
            for i, (title, artist, secs) in enumerate(t_tracks, 1):
                label = f'{title} — {artist}' if artist else title
                lines.append(f'  {i}. {label[:34]:<34}  {fmt(secs)}')
        lines.extend(_stats_records_report(stats, dev_id, width))
    lines.append('')
    lines.append(stats.status_line(bool(cfg and cfg.stats_token)))
    return '\n'.join(lines)


def _stats_records_report(stats, dev_id, width=34, n=8):
    """The all-time record charts: artists / tracks / albums ranked by BOTH time
    and plays, when you listen (weekday x hour), and this month's recap. Play
    counts and album names only exist for listening tracked from v1.7 onward —
    history seeded from the old monthly map has seconds only, so counts are shown
    only where they are real."""
    fmt = stats_module.fmt_mins
    lines = []

    def chart(kind, heading, label_of):
        rows = stats.top_records(kind, n=n, own_device_id=dev_id, by='time')
        if not rows:
            return
        lines.append('')
        lines.append(heading)
        for i, (key, rec) in enumerate(rows, 1):
            plays = f'  {rec["n"]} plays' if rec['n'] else ''
            lines.append(f'  {i}. {label_of(key)[:34]:<34}  {fmt(rec["s"])}{plays}')

    chart('artists', 'Artists — all time', lambda k: k)
    chart('tracks', 'Tracks — all time',
          lambda k: (lambda p: f'{p[1]} — {p[2]}' if len(p) > 2 else k)(k.split('|')))
    chart('albums', 'Albums — all time',
          lambda k: (lambda p: f'{p[0]} — {p[1]}' if len(p) > 1 else k)(k.split('|')))

    # Most-played (by count) is a genuinely different ranking from most-listened.
    played = [r for r in stats.top_records('artists', n=n, own_device_id=dev_id,
                                           by='plays') if r[1]['n']]
    if played:
        lines.append('')
        lines.append('Most played artists')
        for i, (key, rec) in enumerate(played, 1):
            lines.append(f'  {i}. {key[:34]:<34}  {rec["n"]} plays')

    grid, peak = stats.clock_heatmap(own_device_id=dev_id)
    if peak > 0:
        lines.append('')
        lines.append('When you listen  (hour 0 → 23)')
        blocks = ' ░▒▓█'
        for d in range(7):
            row = ''.join(
                blocks[min(4, int(grid[d][h] / peak * 4) + (1 if grid[d][h] else 0))]
                for h in range(24))
            lines.append(f'  {stats_module.WEEKDAY_NAMES[d]}  {row}')

    r = stats.recap(time.strftime('%Y-%m'), own_device_id=dev_id)
    if r['total']:
        lines.append('')
        lines.append(f'Recap {r["label"]}')
        delta = r['total'] - r['previous']
        if r['previous']:
            arrow = '↑' if delta >= 0 else '↓'
            lines.append(f'  {fmt(r["total"])}  ({arrow} {fmt(abs(delta))} vs last month)')
        else:
            lines.append(f'  {fmt(r["total"])}')
        if r['top_artist']:
            lines.append(f'  Top artist  {r["top_artist"][:40]}')
        if r['top_track']:
            lines.append(f'  Top track   {r["top_track"][:40]}')
        if r['new_artists']:
            lines.append(f'  New artists {len(r["new_artists"])}: '
                         + ', '.join(r['new_artists'][:4])[:52])
    return lines


class StatsScreen(ModalScreen):
    """The listen-time report (opened from the map's Stats node)."""
    BINDINGS = [
        Binding('escape', 'dismiss_modal', 'Close'),
        Binding('q', 'dismiss_modal', 'Close'),
    ]

    CSS = """
    #stats-box { width: 84; height: 88%; }
    #stats-scroll { height: 1fr; scrollbar-size-vertical: 1; }
    """

    def __init__(self, stats, cfg):
        super().__init__()
        self._stats = stats
        self._cfg = cfg

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def compose(self) -> ComposeResult:
        with Vertical(id='stats-box', classes='dialog'):
            yield Label('STATS', classes='dialog-title')
            with VerticalScroll(id='stats-scroll'):
                yield Static('', id='stats-view', markup=False)
            yield Label('↑ ↓ PgUp PgDn scroll   ·   Esc / q close',
                        classes='dialog-hint')

    def on_mount(self) -> None:
        self.refresh_stats()

    def refresh_stats(self) -> None:
        try:
            view = self.query_one('#stats-view', Static)
        except NoMatches:
            return
        if self._stats is None:
            view.update('No stats available.')
            return
        # Plain Text (not markup) — device/host names may contain brackets.
        view.update(Text(_stats_report(self._stats, self._cfg)))


class HomeScreen(Screen):
    """The node map: the hub, one node per library area, and the trail of
    lists opened this session. Enter on a node opens its contents as a block
    under it; Enter on a row hands it to the app (`_on_home_result`)."""
    BINDINGS = [
        Binding('escape', 'back', 'Back'),
        Binding('h', 'leave', 'Back'),
        Binding('slash', 'go_search', 'Search'),
        Binding('up', 'move(0,-1)', 'Up'),
        Binding('down', 'move(0,1)', 'Down'),
        Binding('left', 'move(-1,0)', 'Left'),
        Binding('right', 'move(1,0)', 'Right'),
        Binding('pageup', 'page(-8)', 'Page up'),
        Binding('pagedown', 'page(8)', 'Page down'),
        Binding('enter', 'activate', 'Open'),
        Binding('d', 'delete_item', 'Delete'),
        Binding('r,R', 'rename_item', 'Rename'),
        Binding('q', 'quit_app', 'Quit'),
    ]

    CSS = """
    #home-bar { height: 5; padding: 1 2; background: $surface; }
    #home-now { height: 1; color: $text; text-style: bold; }
    #home-status { height: 1; color: $accent; }
    #home-hint { height: 1; color: $text-muted; }
    """

    # Nodes whose rows come straight from the local library.
    _LOCAL = ('resume', 'playlists', 'liked', 'recent')

    def __init__(self, library, stats=None, cfg=None, trail=None):
        super().__init__()
        self._lib = library
        self._stats = stats
        self._cfg = cfg
        self._trail = trail or ([], None, -1)   # (labels, root node, position)
        self._alive = True
        self._db = None         # last audio level from mpv (dB), None = unknown
        self._frames = 0

    def compose(self) -> ComposeResult:
        yield MapCanvas(id='home-map')
        with Vertical(id='home-bar'):
            yield Static('', id='home-now', markup=False)
            yield Static('', id='home-status', markup=False)
            yield Static('', id='home-hint', markup=False)

    def on_mount(self) -> None:
        m = self._map = self.query_one('#home-map', MapCanvas)
        for node in self._LOCAL:
            m.set_rows(node, self._rows_for(node))
        m.set_rows('foryou', [self._note('Loading your feed…')])
        m.set_rows('ytmusic', [self._note('Loading your YouTube Music library…')])
        labels, root, pos = self._trail
        m.set_trail(labels, root, pos)
        if labels and 0 <= pos < len(labels):
            m.select(('trail', pos))    # land on the list you came from
        m.focus()
        self._hint()
        self._draw_now()
        # Fetch the (personalized when signed in) home feed off the UI thread.
        threading.Thread(target=self._load_foryou, daemon=True).start()
        threading.Thread(target=self._load_ytlib, daemon=True).start()
        threading.Thread(target=self._level_loop, daemon=True).start()
        self.set_interval(0.1, self._tick)

    def on_unmount(self) -> None:
        self._alive = False

    # ── Background animation ───────────────────────────────────────────────

    def _playing(self) -> bool:
        app = self.app
        return bool(getattr(app, 'now_playing', '')) and not getattr(app, 'is_paused', False)

    def _level_loop(self) -> None:
        """Daemon thread: sample mpv's audio level ~11x a second while a track
        plays. Off the UI thread because each sample is an IPC round trip."""
        get = getattr(getattr(self.app, '_player', None), 'get_level', None)
        while self._alive:
            db = None
            if get is not None and self._playing():
                try:
                    db = get()
                except Exception:
                    db = None
            self._db = db
            time.sleep(0.09)

    def _tick(self) -> None:
        self._frames += 1
        if self.app.screen is not self:
            return                      # a dialog is on top — draw nothing
        if self._playing():
            db = self._db
            if db is None:
                # No level from the backend (ffplay, or an mpv without the
                # filter): a steady pulse, so it still moves with playback.
                energy = 0.4 + 0.3 * math.sin(self._frames * 0.8)
            else:
                energy = max(0.0, min(1.0, (db + 42.0) / 34.0))
            self._map.tick(energy)
        elif self._frames % 3 == 0:
            self._map.tick(None)        # idle: a slow drift at a third the rate
        if self._frames % 5 == 0:
            self._draw_now()

    def _draw_now(self) -> None:
        app = self.app
        now = getattr(app, 'now_playing', '')
        if now:
            icon = '‖' if getattr(app, 'is_paused', False) else '▸'
            text = (f'{icon}  {now}    {_fmt(getattr(app, "position", 0))}'
                    f' / {_fmt(getattr(app, "duration", 0))}')
        else:
            text = '♪  Nothing playing'
        if text != getattr(self, '_now_text', None):
            self._now_text = text
            try:
                self.query_one('#home-now', Static).update(text)
            except NoMatches:
                pass

    # ── Rows ───────────────────────────────────────────────────────────────

    @staticmethod
    def _note(text):
        return {'label': text, 'payload': None}

    @staticmethod
    def _track_row(track, payload):
        label = f"♪ {track['title']}"
        if track.get('uploader'):
            label += f"  —  {track['uploader']}"
        if track.get('duration'):
            label += f"   {_fmt(track['duration'])}"
        return {'label': label, 'payload': payload}

    def _rows_for(self, node):
        rows = []
        if node == 'resume':
            for s in self._lib.sessions():
                title = s.get('title') or 'session'
                n = len(s.get('queue', []))
                # Sessions synced in from another device carry its name.
                dev = f"  ·  {s['device']}" if s.get('device') else ''
                rows.append({
                    'label': f"▸ {title}  ·  {n} tracks  ·  {_ago(s.get('ts'))}{dev}",
                    'payload': {'kind': 'session', 'id': s.get('id')}})
        elif node == 'playlists':
            for p in self._lib.playlists():
                rows.append({
                    'label': f"♫ {p['name']}  ({len(p['tracks'])})",
                    'payload': {'kind': 'playlist', 'name': p['name']}})
            for path in self._lib.folders():
                rows.append({'label': f'▪ {path}',
                             'payload': {'kind': 'folder', 'path': path}})
        elif node in ('liked', 'recent'):
            tracks = self._lib.liked() if node == 'liked' else self._lib.recent()
            label = 'Liked songs' if node == 'liked' else 'Recent plays'
            rows = [self._track_row(t, {'kind': 'tracklist', 'tracks': tracks,
                                        'index': i, 'label': label})
                    for i, t in enumerate(tracks)]
        return rows or [self._note('— empty —')]

    def _reload(self, node) -> None:
        self._map.set_rows(node, self._rows_for(node))

    def refresh_library(self) -> None:
        """Re-read the library-backed nodes after a cross-device sync applied
        remote changes (new likes/playlists/sessions from other devices)."""
        for node in ('resume', 'playlists', 'liked'):
            self._reload(node)

    def refresh_stats(self) -> None:
        pass        # the report lives in StatsScreen now; kept for the caller

    def _load_foryou(self) -> None:
        err = None
        fallback = False
        try:
            sections = youtube.ytm_home(limit=4)
        except Exception as exc:
            err = f'{type(exc).__name__}: {exc}'
            self._log_feed_error()      # full traceback → err.txt for diagnosis
            sections = []
            # Personalized feed failed — fall back to the generic feed so the
            # node still shows something instead of going blank.
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
        if not self._alive:
            return
        if not sections:
            msg = (f'Feed error: {err}  —  press g to check sign-in' if err else
                   'No feed yet — press g to sign in for your For You feed.')
            self._map.set_rows('foryou', [self._note(msg)])
            return
        rows = []
        if fallback:
            rows.append(self._note(
                f'(personalized feed unavailable: {err}) — showing popular instead'))
        for sec in sections:
            rows.append({'label': sec['title'] or '', 'payload': None,
                         'header': True})
            songs = [it['track'] for it in sec['items'] if it['kind'] == 'song']
            si = 0
            for it in sec['items']:
                if it['kind'] == 'song':
                    rows.append(self._track_row(it['track'], {
                        'kind': 'tracklist', 'tracks': songs,
                        'index': si, 'label': sec['title'] or 'For You'}))
                    si += 1
                else:
                    rows.append({'label': f"♫ {it['name']}", 'payload': {
                        'kind': 'foryou_playlist', 'name': it['name'],
                        'playlistId': it['playlistId']}})
        self._map.set_rows('foryou', rows)

    def _load_ytlib(self) -> None:
        """Fetch the signed-in account's YTM library playlists (daemon thread)."""
        err = None
        playlists = []
        signed_in = youtube.is_authenticated()
        if signed_in:
            try:
                playlists = youtube.ytm_library()
            except Exception as exc:
                err = f'{type(exc).__name__}: {exc}'
        try:
            self.app.call_from_thread(self._populate_ytlib, playlists,
                                      signed_in, err)
        except Exception:
            pass   # screen dismissed before the library arrived

    def _populate_ytlib(self, playlists, signed_in, err=None) -> None:
        if not self._alive:
            return
        if not signed_in:
            rows = [self._note('Sign in (press g) to see your YouTube Music '
                               'library — playlists and likes.')]
        elif err:
            rows = [self._note(f'Library error: {err}  —  press g to check sign-in')]
        else:
            rows = [{'label': '♥ Your Likes', 'payload': {
                'kind': 'foryou_playlist', 'name': 'Your Likes',
                'playlistId': 'LM'}}]
            for p in playlists:
                count = f"  ({p['count']})" if p.get('count') else ''
                rows.append({'label': f"♫ {p['name']}{count}", 'payload': {
                    'kind': 'foryou_playlist', 'name': p['name'],
                    'playlistId': p['playlistId']}})
        self._map.set_rows('ytmusic', rows)

    # ── Navigation ─────────────────────────────────────────────────────────

    def _status(self, msg: str) -> None:
        """Show a one-line feedback message under the map (best-effort)."""
        try:
            self.query_one('#home-status', Static).update(msg)
        except NoMatches:
            pass

    def _hint(self) -> None:
        if self._map.open_id is not None:
            keys = '↑↓ move · enter open'
            if self._map.open_id in self._LOCAL:
                keys += ' · d delete'
            if self._map.open_id == 'playlists':
                keys += ' · r rename'
            keys += ' · ← / esc close'
        else:
            keys = ('←↑↓→ move · enter open · / search · esc back to the list'
                    ' · ? keys · q quit')
        try:
            self.query_one('#home-hint', Static).update(keys)
        except NoMatches:
            pass

    def action_move(self, dx: int, dy: int) -> None:
        self._map.move(dx, dy)
        self._hint()

    def action_page(self, step: int) -> None:
        self._map.page(step)

    def action_back(self) -> None:
        if self._map.close():
            self._hint()
            return
        self.dismiss({'kind': 'back'})

    def action_leave(self) -> None:
        self.dismiss({'kind': 'back'})

    def action_go_search(self) -> None:
        self.dismiss({'kind': 'search'})

    def action_activate(self) -> None:
        m = self._map
        if m.open_id is not None:
            row = m.current_row()
            payload = row.get('payload') if row else None
            if not payload:
                return
            if payload.get('kind') == 'session':
                session = self._lib.get_session(payload.get('id'))
                if session:
                    self.dismiss({'kind': 'resume', 'session': session,
                                  'root': m.open_id})
                return
            self.dismiss(dict(payload, root=m.open_id))
            return
        sel = m.sel
        if isinstance(sel, tuple):
            self.dismiss({'kind': 'trail', 'index': sel[1]})
        elif sel == HUB:
            self.dismiss({'kind': 'back'})
        elif sel == 'search':
            self.dismiss({'kind': 'search'})
        elif sel == 'stats':
            self.app.push_screen(StatsScreen(self._stats, self._cfg))
        elif sel == 'create':
            self._status('Create a mix: not built yet.')
        else:
            m.open_node(sel)
            self._hint()

    # ── Library management (delete / rename) ───────────────────────────────────

    def _confirm(self, message, on_yes) -> None:
        def _cb(ok):
            if ok:
                on_yes()
        self.app.push_screen(ConfirmScreen(message), _cb)

    def _managed_row(self):
        """(node, payload) for the highlighted row of an open, manageable
        node; (node, None) otherwise."""
        node = self._map.open_id
        if node not in self._LOCAL:
            return node, None
        row = self._map.current_row()
        return node, (row.get('payload') if row else None)

    def action_delete_item(self) -> None:
        node, payload = self._managed_row()
        if node not in self._LOCAL:
            self._status('Open Resume, Playlists, Liked or Recent to delete an entry.')
            return
        if not payload:
            self._status('Highlight an item first (↑/↓), then d to delete.')
            return
        kind = payload.get('kind')
        if kind == 'playlist':
            name = payload['name']
            self._confirm(
                f'Delete playlist "{name}"?',
                lambda: (self._lib.delete_playlist(name),
                         self._reload('playlists'),
                         self._status(f'Deleted playlist "{name}".')))
        elif kind == 'folder':
            path = payload['path']
            self._confirm(
                f'Unpin folder?\n{path}',
                lambda: (self._lib.unpin_folder(path),
                         self._reload('playlists'),
                         self._status('Unpinned folder.')))
        elif kind == 'session':
            sid = payload['id']
            self._confirm(
                'Delete this saved session?',
                lambda: (self._lib.delete_session(sid),
                         self._reload('resume'),
                         self._status('Deleted session.')))
        elif kind == 'tracklist':
            # Liked vs Recent — instant (trivially redone), no confirm.
            tracks = payload.get('tracks') or []
            idx = payload.get('index', -1)
            if not (0 <= idx < len(tracks)):
                return
            track = tracks[idx]
            if node == 'liked':
                self._lib.toggle_like(track)        # unlike
                self._status('Removed from Liked.')
            else:
                self._lib.remove_recent(track)
                self._status('Removed from Recent.')
            self._reload(node)

    def action_rename_item(self) -> None:
        _node, payload = self._managed_row()
        if not payload or payload.get('kind') != 'playlist':
            self._status('Open Playlists and highlight a saved playlist to rename.')
            return
        old = payload['name']

        def _cb(new):
            if not new or new == old:
                return
            if self._lib.rename_playlist(old, new):
                self._reload('playlists')
                self._status(f'Renamed to "{new}".')
            else:
                self._status('Rename failed — that name already exists.')

        self.app.push_screen(
            NameScreen(f'Rename playlist "{old}" to:', default=old), _cb)

    def action_quit_app(self) -> None:
        # Route through the app's own quit: a bare app.exit() here skipped the
        # session save, the stats flush AND player.quit(), so quitting from the
        # home screen left the mpv daemon running and still playing.
        self.app.action_quit()


# Everything the command palette (ctrl+p) offers: (name, key, action).
PALETTE = [
    ('Search or paste a URL',            '/',     'focus_search'),
    ('Filter the loaded list',           'f',     'filter'),
    ('Home map',                         'h',     'home'),
    ('Pause / resume',                   'space', 'toggle_pause'),
    ('Next track',                       'n',     'next_track'),
    ('Previous track',                   'b',     'prev_track'),
    ('Stop playback',                    'x',     'stop'),
    ('Seek back 10s',                    '←',     'seek_back'),
    ('Seek forward 10s',                 '→',     'seek_fwd'),
    ('Volume up',                        '+',     'vol_up'),
    ('Volume down',                      '-',     'vol_down'),
    ('Shuffle the queue',                'z',     'shuffle'),
    ('Repeat: off / one / all',          'r',     'cycle_repeat'),
    ('Radio from this track',            'R',     'radio'),
    ('Play highlighted track next',      'p',     'play_next'),
    ('Add highlighted track to queue',   'a',     'add_queue'),
    ('Queue / list view',                'Q',     'toggle_view'),
    ('Like / unlike',                    'l',     'like'),
    ('Lyrics',                           'L',     'lyrics'),
    ('Artist page',                      'A',     'artist'),
    ('Save list as a playlist',          'w',     'save_playlist'),
    ('Search source: YT Music / YouTube / both', 't', 'cycle_source'),
    ('Online / offline mode',            'o',     'toggle_mode'),
    ('Theme picker',                     'c',     'theme_picker'),
    ('Next theme',                       'C',     'cycle_theme'),
    ('Account / sign in',                'g',     'account'),
    ('Stats sync settings',              's',     'settings'),
    ('Check for updates',                'u',     'update'),
    ('Changelog',                        'V',     'changelog'),
    ('Keyboard shortcuts',               '?',     'show_keys'),
    ('Quit',                             'q',     'quit'),
]


class AppCommands(Provider):
    """Command palette source: the app's own actions, nothing else."""

    def _hits(self):
        app = self.app
        for name, key, action in PALETTE:
            if app.check_action(action, ()) is False:
                continue        # doesn't apply on this screen
            yield name, key, (lambda a=action: app.run_action(a))

    async def discover(self):
        for name, key, run in self._hits():
            yield DiscoveryHit(name, run, help=f'key: {key}')

    async def search(self, query: str):
        matcher = self.matcher(query)
        for name, key, run in self._hits():
            score = matcher.match(name)
            if score > 0:
                yield Hit(score, matcher.highlight(name), run,
                          help=f'key: {key}')


# ── Main App ──────────────────────────────────────────────────────────────────

class YTMApp(App):
    """YouTube Music TUI."""

    TITLE = 'YouTube Music TUI'

    # Borderless blocks: every part is its own shade under a one-line label
    # bar, and the label of the part that has focus turns accent. On a tall
    # terminal (`-tall`, see on_resize) a blank row separates the parts too.
    CSS = """
    Screen { layout: vertical; background: $background; }
    ModalScreen { align: center middle; background: $background 70%; }

    .dialog { padding: 1 2; background: $panel; }
    .dialog-title { text-style: bold; color: $accent; margin-bottom: 1; }
    .dialog-hint { color: $text-muted; }

    Input { border: none; height: 1; padding: 0 1; background: $boost; }
    Input:focus { border: none; background: $accent 18%; }
    ModalScreen Input { margin-bottom: 1; }
    Button { border: none; height: 1; min-width: 8; padding: 0 2;
             background: $boost; color: $text; }
    Button:hover { border: none; background: $accent 30%; }
    Button:focus { border: none; background: $accent 45%; text-style: bold; }
    Button.-primary { background: $accent; color: $background; text-style: bold; }
    Button.-primary:focus { background: $accent; text-style: bold underline; }
    ModalScreen Button { margin-right: 2; }
    OptionList { border: none; background: $surface; }
    OptionList:focus { border: none; }

    DataTable { background: $surface; overflow-x: hidden;
                scrollbar-size-vertical: 1; }
    DataTable > .datatable--header { background: $surface; color: $text-muted;
                                     text-style: none; }
    DataTable > .datatable--cursor { background: $accent 16%; }
    DataTable:focus > .datatable--cursor { background: $accent 34%; }
    DataTable > .datatable--hover { background: $boost; }

    .blk { background: $surface; }
    .blk-label { height: 1; padding: 0 1; background: $boost;
                 color: $text-muted; text-style: bold; }
    .blk.active .blk-label { color: $accent; }

    #topbar { height: 1; padding: 0 1; background: $panel; }
    #topbar-left { width: 1fr; }
    #topbar-right { width: auto; color: $text-muted; }

    #search-row { height: 1; background: $surface; }
    #search-tag { width: 10; }
    #search-input { width: 1fr; }
    #source-btn { width: auto; min-width: 12; }

    #filter-row { height: 1; background: $surface; display: none; }
    #filter-row.visible { display: block; }
    #filter-tag { width: 10; }
    #filter-input { width: 1fr; }

    #main-row { height: 1fr; }
    #lists { width: 1fr; height: 1fr; }
    #search-pane { height: 1fr; display: none; }
    #search-pane.visible { display: block; }
    #search-head { height: 1; background: $boost; }
    #search-label { width: 1fr; }
    #search-close { width: auto; min-width: 14; background: $boost; }
    #list-pane { height: 1fr; }
    #results-table, #search-table { width: 1fr; height: 1fr; border: none; }

    /* Cover art, right of the lists. Hidden by default: _sync_art_panel
       shows it (and sets its width) only when the terminal is wide enough.
       Top two thirds: what's playing. Bottom third: whatever the cursor is on. */
    #art-panel { display: none; width: 0; margin-left: 1; }
    #art-panel.visible { display: block; }
    #art-now { height: 2fr; padding: 1 2 0 2; }
    #art-cursor { height: 1fr; padding: 1 2 0 2; }
    #art-image, #art-cursor-image { height: auto; text-align: center; }
    #art-title { height: auto; color: $text; text-style: bold; margin-top: 1; }
    #art-artist { height: auto; color: $text-muted; }
    #art-album { height: auto; color: $text-muted; text-style: italic; }
    #art-facts { height: auto; color: $accent; }
    #art-you { height: auto; color: $text-muted; }
    #art-cursor-title { height: auto; color: $text-muted; margin-top: 1; }

    #player-bar { height: auto; background: $panel; }
    #player-label { display: none; }
    #player-rows { height: 4; padding: 0 2; }
    #now-playing { height: 1; color: $text; text-style: bold; }
    #controls-row { height: 1; color: $text-muted; }
    #progress-row { height: 1; color: $accent; }
    #status-row { height: 1; color: $text-muted; }

    #footer-bar { height: 1; padding: 0 1; background: $background; }
    #footer-left { width: 1fr; color: $text-muted; }
    #footer-right { width: auto; color: $accent; text-style: bold; }

    .-tall #search-row, .-tall #main-row, .-tall #player-bar { margin-top: 1; }
    .-tall #list-pane.split { margin-top: 1; }
    .-tall #player-label { display: block; }
    """

    # ctrl+p: every action by name, with its key. The stock palette listed
    # Textual's own commands, including a Quit that skipped ours.
    COMMANDS = {AppCommands}

    BINDINGS = [
        Binding('slash', 'focus_search', 'Search', show=False),
        Binding('f', 'filter', 'Filter', show=False),
        Binding('space', 'toggle_pause', 'Pause', show=False),
        Binding('n', 'next_track', 'Next', show=False),
        Binding('b', 'prev_track', 'Previous', show=False),
        Binding('a', 'add_queue', '+Queue', show=False),
        Binding('p', 'play_next', 'Play next', show=False),
        Binding('x', 'stop', 'Stop', show=False),
        Binding('Q', 'toggle_view', 'Queue/Library', show=False),
        # Reorder the queue. K/J are the portable primary (macOS grabs ctrl+arrows for
        # Mission Control; some terminals eat alt+arrows) — shift+arrows work in most
        # modern terminals and are kept as a natural alias.
        Binding('K,shift+up', 'move_track_up', 'Move up', show=False),
        Binding('J,shift+down', 'move_track_down', 'Move down', show=False),
        Binding('z', 'shuffle', 'Shuffle', show=False),
        Binding('r', 'cycle_repeat', 'Repeat', show=False),
        Binding('l', 'like', 'Like', show=False),
        Binding('L', 'lyrics', 'Lyrics', show=False),
        Binding('A', 'artist', 'Artist', show=False),
        Binding('R', 'radio', 'Radio', show=False),
        Binding('w', 'save_playlist', 'Save playlist', show=False),
        Binding('h', 'home', 'Home', show=False),
        Binding('t', 'cycle_source', 'Source', show=False),
        Binding('o', 'toggle_mode', 'Online/Offline', show=False),
        Binding('c', 'theme_picker', 'Theme', show=False),
        Binding('C', 'cycle_theme', 'Cycle theme', show=False),
        Binding('plus,equals_sign', 'vol_up', 'Vol+', show=False),
        Binding('minus', 'vol_down', 'Vol-', show=False),
        Binding('left', 'seek_back', 'Seek-', show=False),
        Binding('right', 'seek_fwd', 'Seek+', show=False),
        Binding('s', 'settings', 'Settings', show=False),
        Binding('g', 'account', 'Account', show=False),
        Binding('u', 'update', 'Update', show=False),
        Binding('V', 'changelog', 'Changelog', show=False),
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
        # Listen-time stats: local counters + optional gist sync (see stats.py).
        self._stats = stats_module.StatsStore()
        if not self._config.stats_device_id:
            import uuid
            self._config.stats_device_id = uuid.uuid4().hex
        if not self._config.stats_device_name:
            import platform
            self._config.stats_device_name = platform.node().split('.')[0] or 'desktop'
        self._stats_last = None   # (queue_idx, position) at the previous poll tick
        self._mediakeys = None    # OS media-keys backend (set by _init_player)
        self._recovering = False       # one mpv/IPC recovery in flight
        self._last_recover_ts = 0.0    # monotonic; cooldown to avoid respawn storms
        self._app_nap_token = None     # macOS NSProcessInfo activity (held for life)
        self._stats_syncing = False   # a gist sync is in flight (footer ⟳)
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
        self._search_artists = []   # top artist matches from the last keyword search
        self._search_albums  = []   # top album/playlist matches from the last search
        self._last_query = ''
        # The search pane (upper half while open) has its own results and its
        # own generation counter: a search no longer replaces the loaded list,
        # so it must not cancel a playlist that is still arriving either.
        self._search_results = []
        self._search_open = False
        self._search_gen = 0
        # Lists opened this session, oldest first: [{'label', 'tracks'}]. The
        # home map draws it as a chain off `_trail_root` (the node the first
        # one was picked from) and can jump back to any of them.
        self._trail = []
        self._trail_root = None
        self._trail_pos = -1
        self._col_sig = {}        # table id -> (title, artist) widths in use
        self._clock = ''
        # Bumped by every search / playlist / album / folder load. A worker
        # only applies its result while its own number is still the current
        # one, so a slow earlier request can't overwrite what was asked next.
        self._load_gen = 0
        self._cfg_timer = None
        self._update_available = False   # set by the boot-time update check
        self._restart_requested = False  # set when an update asks for a relaunch
        # Polled playback state (plain attrs — see note on the reactive block).
        self.position = 0.0
        self.duration = 0.0
        self.is_paused = False
        self._last_bar_sig = None        # skip redundant player-bar redraws
        self._loading_since = None       # monotonic ts while awaiting playback (load watchdog)
        self._play_timer = None          # debounce timer for rapid selections (misclicks)
        self._premium_retry_id = None    # track id already retried with account cookies
        # Cover-art panel state (see _sync_art_panel): last drawn
        # (track, cols, rows), and the track ids with a download in flight.
        self._art_sig = None
        self._art_fetching = set()
        self._cursor_track = None     # row under the table cursor (lower half)
        self._cursor_since = 0.0      # when it landed there — debounces fetches
        self._details = {}            # track key -> {album, year, views} (cached)
        self._details_fetching = set()
        # Color-wave animation state (see _sync_animation / _animate_tick).
        self._anim_frame = 0
        self._anim_timer = None          # active Timer while the wave is running
        self._playing_row = None         # displayed row index of the playing track
        self.search_source = self._config.search_source
        self.volume        = self._config.volume
        self.app_mode      = self._config.app_mode
        # OAuth is dead (YouTube rejects the tokens with HTTP 400 — verified) and is no
        # longer offered in the UI, so a stored 'oauth' method would just 400 every feed
        # call. Migrate it to 'none' once; the user re-signs-in via Browser or Cookies.
        if self._config.auth_method == 'oauth':
            self._config.auth_method = 'none'
            self._config.account_name = ''
        # Wire the saved auth method (browser / cookies / none) so ytmusicapi calls
        # run authenticated when configured (personalized search / For You feed).
        youtube.configure_auth(self._config.auth_method,
                               self._config.auth_cookies_file,
                               browser=self._config.auth_browser,
                               profile=self._config.auth_browser_profile)

    # ── Layout ────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        # markup=False on everything that shows a title: track names are
        # data. Read as markup, "song [lyrics]" loses its tag and a title
        # holding "[/x]" raises MarkupError and takes the app down.
        with Horizontal(id='topbar'):
            yield Static('', id='topbar-left', markup=False)
            yield Static('', id='topbar-right', markup=False)
        with Horizontal(id='search-row'):
            yield Static('SEARCH', id='search-tag', classes='blk-label')
            yield Input(placeholder='Search or paste URL…', id='search-input')
            yield Button(SOURCE_LABEL[self.search_source], id='source-btn',
                         variant='default')
        with Horizontal(id='filter-row'):
            yield Static('FILTER', id='filter-tag', classes='blk-label')
            yield Input(placeholder='Filter loaded list… (Esc to clear)',
                        id='filter-input')
        # cursor_foreground_priority='renderable' so the playing row's accent
        # color (set in _row_cells) survives even when it's also the cursor row;
        # the default 'css' lets the cursor style override it (Bug: no highlight).
        with Horizontal(id='main-row'):
            with Vertical(id='lists'):
                with Vertical(id='search-pane', classes='blk'):
                    with Horizontal(id='search-head'):
                        yield Static('SEARCH', id='search-label',
                                     classes='blk-label', markup=False)
                        yield Button('✕ close (esc)', id='search-close')
                    yield DataTable(id='search-table', cursor_type='row',
                                    cursor_foreground_priority='renderable')
                with Vertical(id='list-pane', classes='blk'):
                    yield Static('LIST', id='list-label', classes='blk-label',
                                 markup=False)
                    yield DataTable(id='results-table', cursor_type='row',
                                    cursor_foreground_priority='renderable')
            with Vertical(id='art-panel', classes='blk'):
                yield Static('NOW PLAYING', classes='blk-label')
                with Vertical(id='art-now'):
                    yield Static('', id='art-image', markup=False)
                    yield Static('', id='art-title', markup=False)
                    yield Static('', id='art-artist', markup=False)
                    yield Static('', id='art-album', markup=False)
                    yield Static('', id='art-facts', markup=False)
                    yield Static('', id='art-you', markup=False)
                yield Static('UNDER CURSOR', classes='blk-label')
                with Vertical(id='art-cursor'):
                    yield Static('', id='art-cursor-image', markup=False)
                    yield Static('', id='art-cursor-title', markup=False)
        with Vertical(id='player-bar'):
            yield Static('PLAYER', id='player-label', classes='blk-label')
            with Vertical(id='player-rows'):
                yield Static('♪  Nothing playing', id='now-playing', markup=False)
                yield Static('', id='controls-row', markup=False)
                yield Static('', id='progress-row', markup=False)
                yield Static(self.status_msg, id='status-row', markup=False)
        with Horizontal(id='footer-bar'):
            yield Static('', id='footer-left')
            yield Static('? keys · ^p commands', id='footer-right')

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
        for tid in ('#results-table', '#search-table'):
            self._add_columns(self.query_one(tid, DataTable), 45, 25)
        self._update_topbar()
        self._update_list_label()
        # The pane that has the focus shows its label in the accent color.
        self.watch(self.screen, 'focused', self._mark_active_pane)
        self.set_interval(1.0, self._poll_player)
        self.set_interval(60.0, self._stats_flush)
        self.set_interval(600.0, self._stats_sync_maybe)
        self.set_timer(8.0, self._stats_sync_maybe)   # boot pull of other devices
        self._begin_app_nap_suppression()   # macOS: keep our IPC loop off App Nap
        self._update_mode_ui()
        self._update_footer()
        threading.Thread(target=self._init_player, daemon=True).start()
        threading.Thread(target=self._check_for_update, daemon=True).start()
        # If signed in, live-verify the session — but only when the last successful
        # check is stale (>12h): the network round-trip costs 3-5s at every boot,
        # and a session that verified this morning doesn't need re-proving. Expiry
        # mid-window still surfaces (feed errors show 'press g to check sign-in').
        if (youtube.is_authenticated()
                and time.time() - self._config.auth_verified_ts > 12 * 3600):
            threading.Thread(target=self._verify_account, daemon=True).start()
        # Boot straight into the home screen.
        self.action_home()

    def _verify_account(self, signing_in: bool = False) -> None:
        """Confirm the live session in the background. `signing_in` marks the run
        kicked off by the Account screen, which must always end in a visible
        outcome — at boot the same check stays quiet unless something is wrong."""
        status, name = youtube.verify_auth_live()

        def _apply():
            method = self._config.auth_method
            detail = youtube.auth_detail()
            if status == 'ok' and name:
                self._config.account_name = name
                self._config.auth_verified_ts = time.time()
                if signing_in:
                    self._set_status(f'Signed in as {name}.')
            elif status == 'expired':
                # Not authenticating → drop the stale name (is_authenticated is now
                # False, so the footer hides the account) and say WHY, per method.
                # `detail` names the real cause when the session never even loaded:
                # unreadable cookie store, wrong browser profile, signed-out browser.
                self._config.account_name = ''
                self._config.auth_verified_ts = 0.0
                if method == 'browser':
                    why = detail or 'that browser profile is signed out of YouTube'
                    self._set_status(f'⚠ Not signed in — {why}. Sign into '
                                     'music.youtube.com in that browser profile, '
                                     'then press g and pick it again.')
                else:
                    why = detail or 'your saved cookies no longer work'
                    self._set_status(f'⚠ YouTube sign-in expired — {why}. '
                                     'Press g to re-export cookies.txt.')
            elif signing_in:
                # 'unknown' = couldn't confirm (network/transient). The cached name
                # is left alone, but a sign-in the user just asked for must not end
                # in silence — that read as "it closed and nothing happened".
                self._set_status('Could not confirm the sign-in (network?) — '
                                 'the app will re-check. Press g to try again.')
            self._update_footer()

        try:
            self.call_from_thread(_apply)
        except Exception:
            pass

    def _init_player(self) -> None:
        if self._player.backend is None:
            self.call_from_thread(
                self._set_status,
                'No audio backend found — install mpv ('
                + player_module.install_hint() + ') to enable playback.'
            )
            return
        if self._player.backend == 'ffplay':
            self.call_from_thread(
                self._set_status,
                'Using ffplay (limited controls: no seek/volume/position). Install mpv for full control.'
            )
        # Before the spawn: the daemon starts at this level (--volume) rather
        # than at 100% with a correction racing the first track.
        self._player.set_volume(self.volume)
        self._player._ensure_mpv_running()
        # OS media keys + now-playing panel (Control Center / MPRIS / SMTC).
        # Optional: returns None when the per-OS dep isn't installed — the app
        # behaves exactly as before. Callbacks arrive on backend threads.
        self._mediakeys = mediakeys.start({
            'play': lambda: self.call_from_thread(self._media_play),
            'pause': lambda: self.call_from_thread(self._media_pause),
            'toggle_pause': lambda: self.call_from_thread(self.action_toggle_pause),
            'next': lambda: self.call_from_thread(self.action_next_track),
            'previous': lambda: self.call_from_thread(self.action_prev_track),
            'stop': lambda: self.call_from_thread(self.action_stop),
        })

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
        # A toast too — the status line is easy to miss (and the HomeScreen covers it
        # at boot, which is exactly when this check lands).
        try:
            self.notify(f'{behind} new commit(s) available — press u to update.',
                        title='↑ Update available', timeout=8)
        except Exception:
            pass

    # ── Listen-time stats ──────────────────────────────────────────────────

    def _stats_flush(self) -> None:
        self._stats.flush()

    def _stats_sync_maybe(self, announce: bool = False) -> None:
        """Kick a gist sync on a daemon thread. No-op without a token; the
        periodic timer is throttled so a fresh manual sync isn't repeated."""
        if not self._config.stats_token:
            return
        if not announce and time.time() - self._stats.last_sync() < 540:
            return
        if self._stats_syncing:
            return
        self._stats_syncing = True
        self._update_footer()
        # Snapshot the library HERE, on the UI thread: Library isn't thread-safe,
        # and exporting from the worker could copy a dict the UI is mutating
        # (liking a track mid-sync) — that raises "dictionary changed size".
        export = self._lib.export_sync(device_name=self._config.stats_device_name)
        threading.Thread(target=self._stats_sync_worker, args=(announce, export),
                         daemon=True).start()

    def _stats_sync_worker(self, announce: bool = False, export=None) -> None:
        # The library blob (liked/playlists/sessions + tombstones) rides in our
        # gist file; the sync returns everyone's merged state to apply locally.
        ok, msg, new_id, merged_lib = self._stats.sync(
            self._config.stats_token, self._config.stats_device_id,
            self._config.stats_device_name, self._config.stats_gist_id,
            library_export=export)

        def _apply():
            self._stats_syncing = False
            self._update_footer()
            if new_id:
                self._config.stats_gist_id = new_id
            if announce:
                self._set_status('Stats sync: connected ✓' if ok
                                 else f'Stats sync: {msg}')
            # Apply the merged library on the UI thread (Library isn't
            # thread-safe) and refresh any home tabs showing it.
            if ok and merged_lib is not None:
                changed = self._lib.apply_sync(
                    merged_lib, own_device_name=self._config.stats_device_name)
                if changed and isinstance(self.screen, HomeScreen):
                    self.screen.refresh_library()
            if isinstance(self.screen, HomeScreen):
                self.screen.refresh_stats()
            # Live-refresh the sync panel's graph if it's open.
            if isinstance(self.screen, SettingsScreen):
                self.screen.refresh_stats()

        try:
            self.call_from_thread(_apply)
        except Exception:
            self._stats_syncing = False

    # ── Home screen result ─────────────────────────────────────────────────

    def _on_home_result(self, result) -> None:
        if not result:
            return
        kind = result.get('kind')
        root = result.get('root')
        if kind == 'search':
            self.query_one('#search-input', Input).focus()
            return
        if kind == 'back':
            self._focus_list()
            return
        if kind == 'trail':
            self._goto_trail(result.get('index', -1))
            return
        self._new_load()    # a playlist still in flight must not replace this
        if kind == 'resume':
            self._resume_session(result['session'], root)
        elif kind == 'playlist':
            pl = self._lib.get_playlist(result['name'])
            if pl:
                self._open_list(result['name'], pl['tracks'], root)
        elif kind == 'folder':
            self.app_mode = 'offline'
            self._config.app_mode = 'offline'
            self._update_mode_ui()
            self._do_scan_folder(result['path'], root)
        elif kind == 'tracklist':
            tracks = result['tracks']
            self._open_list(result.get('label') or 'List', tracks, root)
            self._set_queue(tracks)
            self._play_queue_item(result.get('index', 0))
        elif kind == 'foryou_playlist':
            self._do_load_playlist(result['playlistId'],
                                   result.get('name') or 'Playlist', root)

    # ── Trail: the lists opened this session ───────────────────────────────

    def _place(self, label, tracks, root=None) -> None:
        """Record that `tracks` is now the loaded list. Picked from a home
        node (`root`), it starts a new trail there; opened from inside the
        listening view (album, radio, artist, search) it extends the current
        one, dropping whatever lay ahead of the position we branched from."""
        entry = {'label': label or 'List', 'tracks': tracks}
        if root or not self._trail:
            self._trail = [entry]
            self._trail_root = root or 'search'
        else:
            del self._trail[self._trail_pos + 1:]
            if self._trail and self._trail[-1]['label'] == entry['label']:
                self._trail[-1] = entry
            else:
                self._trail.append(entry)
            del self._trail[:-8]
        self._trail_pos = len(self._trail) - 1
        self._update_list_label()
        self._update_topbar()

    def _open_list(self, label, tracks, root=None) -> None:
        self._populate_results(tracks)
        self._place(label, tracks, root)

    def _goto_trail(self, index) -> None:
        """Back (or forward) to a list on the trail. Only the list changes:
        whatever is playing keeps playing from its own queue."""
        if not 0 <= index < len(self._trail):
            return
        self._new_load()
        self._trail_pos = index
        entry = self._trail[index]
        self._populate_results(entry['tracks'])
        self._update_list_label()
        self._update_topbar()
        self._set_status(f'Back to {entry["label"]} — Enter on a song to play')

    def _place_label(self) -> str:
        if 0 <= self._trail_pos < len(self._trail):
            return self._trail[self._trail_pos]['label']
        return ''

    def _mark_active_pane(self, focused=None) -> None:
        fid = getattr(focused, 'id', '') or ''
        for pane, ids in (('#search-pane', ('search-table', 'search-close')),
                          ('#list-pane', ('results-table',))):
            try:
                self.query_one(pane).set_class(fid in ids, 'active')
            except NoMatches:
                pass

    def _focus_list(self) -> None:
        try:
            self.query_one('#results-table', DataTable).focus()
        except NoMatches:
            pass

    def _resume_session(self, session, root=None) -> None:
        queue = session.get('queue') or []
        if not queue:
            self._set_status('Session had no tracks.')
            return
        self.app_mode = session.get('app_mode', 'online')
        self._config.app_mode = self.app_mode
        self.shuffle = bool(session.get('shuffle', False))
        self.repeat = session.get('repeat', 'off')
        self._update_mode_ui()
        self._open_list(session.get('title') or 'Session', queue, root)
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

        # Results go to the search pane (upper half); the loaded list stays
        # where it is underneath.
        self._set_status(f'Searching "{query}"…')
        self._last_query = query
        self._search_results = []
        self._search_artists = []
        self._search_albums = []
        self._search_gen += 1
        gen = self._search_gen
        self._open_search()
        self._render_search()

        def _land(fn, *args):
            def _apply():
                if gen == self._search_gen and self._search_open:
                    fn(*args)
            self.call_from_thread(_apply)

        def _run():
            try:
                results = youtube.resolve(
                    query,
                    source=self.search_source,
                    cookies_file=self._config.valid_cookies(),
                    max_results=self._config.max_results,
                )
                _land(self._set_search_results, results)
            except Exception as exc:
                _land(self._set_status, f'Search error: {exc}')

        threading.Thread(target=_run, daemon=True).start()

        # In parallel, look up the top artist/album matches (online YTM only) so 'A' can
        # open the artist page. Best-effort; never blocks the song results.
        if self.app_mode != 'offline' and not youtube._is_url(query):
            def _entities():
                try:
                    ent = youtube.ytm_search_entities(query)
                    _land(self._set_search_entities,
                          ent.get('artists') or [], ent.get('albums') or [])
                except Exception:
                    pass
            threading.Thread(target=_entities, daemon=True).start()

    def _open_search(self) -> None:
        self._search_open = True
        try:
            self.query_one('#search-pane').add_class('visible')
            self.query_one('#list-pane').add_class('split')
        except NoMatches:
            return
        self._update_search_label()
        self.call_after_refresh(self._fit_columns)

    def _close_search(self) -> None:
        """Hide the search pane and give the list its full height back."""
        if not self._search_open:
            return
        self._search_open = False
        self._search_gen += 1           # a search still in flight lands nowhere
        self._search_results = []
        self._search_artists = []
        self._search_albums = []
        try:
            self.query_one('#search-pane').remove_class('visible')
            self.query_one('#list-pane').remove_class('split')
        except NoMatches:
            return
        self._focus_list()
        self.call_after_refresh(self._fit_columns)

    def _update_search_label(self) -> None:
        n = len(self._search_results)
        text = f'SEARCH · {self._last_query}'
        if n:
            text += f' · {n} result{"s" if n != 1 else ""}'
        try:
            self.query_one('#search-label', Static).update(text)
        except NoMatches:
            pass

    def _set_search_results(self, results) -> None:
        self._search_results = results
        self._update_search_label()
        self._render_search()
        if not results:
            self._set_status('No results found.')
            return
        self._set_status(
            f'{len(results)} result(s) — Enter play · a queue · p next · Esc close')
        self.query_one('#search-table', DataTable).focus()

    def _set_search_entities(self, artists, albums) -> None:
        self._search_artists = artists
        self._search_albums = albums
        if artists or albums:
            self._render_search()

    def _render_search(self) -> None:
        try:
            tbl = self.query_one('#search-table', DataTable)
        except NoMatches:
            return
        try:
            saved = tbl.cursor_row
        except Exception:
            saved = 0
        tbl.clear()
        count = self._render_entity_rows(tbl)   # artist/album rows on top
        entities = count
        playing_key = self._playing_key()
        for i, r in enumerate(self._search_results):
            playing = playing_key is not None and _track_key(r) == playing_key
            dur = _fmt(r['duration']) if r['duration'] else '?'
            tbl.add_row(*self._row_cells('▸' if playing else str(i + 1),
                                         r['title'], r['uploader'], dur, playing),
                        key=f's{i}')
            count += 1
        if count:
            # First landing: start on the first song, not on an artist row.
            row = saved if saved else (entities if entities < count else 0)
            tbl.move_cursor(row=min(row, count - 1))

    def _play_search_hit(self, i: int) -> None:
        """Enter on a search result. With a list loaded, the song plays now
        and the list (and the rest of the queue) is left alone. With nothing
        loaded, the results themselves become the list."""
        if not 0 <= i < len(self._search_results):
            return
        track = self._search_results[i]
        if not self._results:
            tracks = list(self._search_results)
            label = f'Search: {self._last_query}'
            self._close_search()
            self._new_load()
            self._open_list(label, tracks)
            self._set_queue(tracks)
            self._play_queue_item(i)
            return
        at = (self._queue_idx + 1
              if self.now_playing and 0 <= self._queue_idx < len(self._queue)
              else len(self._queue))
        self._queue.insert(at, track)
        self._play_queue_item(at)
        self._render_search()

    def _new_load(self) -> int:
        self._load_gen += 1
        return self._load_gen

    def _land(self, gen, fn, *args) -> None:
        """Worker thread → UI thread, unless a newer load has started since."""
        def _apply():
            if gen == self._load_gen:
                fn(*args)
        self.call_from_thread(_apply)

    def _do_load_playlist(self, playlist_id: str, label='Playlist', root=None) -> None:
        """Load a large playlist: show first page fast (ytmusicapi), then all.
        Falls back to yt-dlp for playlists ytmusicapi can't serve (non-music)."""
        self._set_status('Loading playlist… first tracks')
        self._results = []
        gen = self._new_load()

        def _run():
            first = []
            try:
                first = youtube.ytm_playlist(playlist_id, limit=100)
                if first:
                    self._land(gen, self._open_list, label, first, root)
                    self._land(gen, self._set_status,
                               f'{len(first)} tracks loaded — fetching the rest…')
                full = youtube.ytm_playlist(playlist_id, limit=None)
                if full:
                    self._land(gen, self._playlist_rest, first, full)
                    return
                raise RuntimeError('ytmusicapi returned no tracks')
            except Exception:
                if first:
                    return      # the first page is up; keep it
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
                    self._land(gen, self._open_list, label, results, root)
                except Exception as exc:
                    self._land(gen, self._set_status, f'Playlist error: {exc}')

        threading.Thread(target=_run, daemon=True).start()

    def _playlist_rest(self, first, full) -> None:
        """The whole playlist has arrived behind its first page. By now the
        user may be listening, filtering or looking at the queue, so this
        swaps the list in underneath them: no focus grab, no view switch.

        If playback was started from the first page, the queue is that page
        (100 tracks) and would simply end there — so it grows to the whole
        playlist, provided it's still the untouched first page."""
        if len(full) <= len(first):
            return
        ids = [_track_key(t) for t in first]
        if ([_track_key(t) for t in self._queue] == ids
                and [_track_key(t) for t in full[:len(first)]] == ids):
            self._queue = self._queue + full[len(first):]
        for entry in self._trail:       # the trail holds the first page too
            if entry['tracks'] is first:
                entry['tracks'] = full
        self._results = full
        self._render_table()
        self._update_footer()
        self._last_bar_sig = None       # the n/total counter changed
        self._set_status(f'{len(full)} tracks loaded')

    def _do_scan_folder(self, path: str, root=None) -> None:
        self._set_status(f'Scanning {path}…')
        self._results = []
        gen = self._new_load()

        def _run():
            try:
                from offline import scan_folder
                results = scan_folder(path)
                label = os.path.basename(path.rstrip('/\\')) or path
                self._land(gen, self._open_list, label, results, root)
                if results:
                    # UI thread: Library isn't thread-safe.
                    self.call_from_thread(self._lib.pin_folder, path)
                else:
                    self._land(gen, self._set_status,
                               f'No audio files found in: {path}')
            except Exception as exc:
                self._land(gen, self._set_status, f'Scan error: {exc}')

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
        mode_label = 'file(s)' if self.app_mode == 'offline' else 'track(s)'
        self._set_status(f'{len(results)} {mode_label} — Enter to play')
        if not self._search_open:
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
        # Text, not str: DataTable parses a str cell as markup (see compose).
        return [Text(str(marker)), Text(title), Text(artist), Text(dur)]

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
        self._update_list_label()

    def _update_list_label(self) -> None:
        if self.view_mode == 'queue':
            text = f'QUEUE · {len(self._queue)} tracks · Q back to the list'
        else:
            name = self._place_label()
            text = 'LIST' + (f' · {name}' if name else '')
            if self._results:
                shown = len(self._visible_results())
                total = len(self._results)
                text += (f' · {shown} of {total}' if shown != total
                         else f' · {total} tracks')
        try:
            self.query_one('#list-label', Static).update(text)
        except NoMatches:
            pass

    def _update_topbar(self) -> None:
        left = Text('♫ YTTUI', style=f'bold {self._accent()}', no_wrap=True)
        crumbs = [e['label'] for e in self._trail[:self._trail_pos + 1]]
        if crumbs:
            left.append('   ' + '  ›  '.join(crumbs[-3:]), style='dim')
        self._clock = time.strftime('%H:%M')
        try:
            self.query_one('#topbar-left', Static).update(left)
            self.query_one('#topbar-right', Static).update(self._clock)
        except NoMatches:
            pass

    # ── Column fitting ─────────────────────────────────────────────────────

    @staticmethod
    def _add_columns(tbl, title_w, artist_w) -> None:
        tbl.add_column('#',        width=4)
        tbl.add_column('Title',    width=title_w)
        tbl.add_column('Artist',   width=artist_w)
        tbl.add_column('Time',     width=6)

    def _fit_columns(self) -> None:
        """Size Title and Artist to the table, so the columns never add up to
        more than the pane. A table wider than its pane scrolls sideways, and
        a table that can scroll sideways swallows ← and → — which are seek."""
        for tid, render in (('results-table', self._render_table),
                            ('search-table', self._render_search)):
            try:
                tbl = self.query_one('#' + tid, DataTable)
            except NoMatches:
                continue
            width = tbl.size.width
            if width <= 0:
                continue
            # 4 + 6 fixed, 2 cells of padding per column, 1 for the scrollbar.
            room = max(12, width - 10 - 8 - 1)
            title_w = max(8, int(room * 0.62))
            artist_w = max(4, room - title_w)
            if self._col_sig.get(tid) == (title_w, artist_w):
                continue
            self._col_sig[tid] = (title_w, artist_w)
            tbl.clear(columns=True)
            self._add_columns(tbl, title_w, artist_w)
            render()

    def _render_entity_rows(self, tbl) -> int:
        """Put the top artist(s) + a few albums above the search results so an artist is
        reachable straight from search (online only). Rows are keyed 'A:<channelId>' /
        'B:<browseId>'; returns rows added."""
        if self.app_mode == 'offline':
            return 0
        accent = self._accent()
        added = 0
        for a in self._search_artists[:3]:
            cid = a.get('channelId')
            if not cid:
                continue
            tbl.add_row(Text('◆', style=f'bold {accent}'),
                        Text(a.get('name') or '', style=f'bold {accent}'),
                        Text('artist', style=accent), Text('↵', style=accent),
                        key=f'A:{cid}')
            added += 1
        for al in self._search_albums[:4]:
            bid = al.get('browseId')
            if not bid:
                continue
            sub = al.get('artist') or (al.get('kind') or 'album')
            tbl.add_row(Text('◇', style=accent), Text(al.get('name') or '', style=accent),
                        Text(sub, style='dim'), Text('↵', style='dim'), key=f'B:{bid}')
            added += 1
        return added

    def _highlighted_track(self):
        """Return (kind, index, track) for the row under the cursor of the
        table that has focus (the list, unless the search pane does), or None."""
        if self._search_open and getattr(self.focused, 'id', '') == 'search-table':
            tbl = self.focused
            try:
                key = tbl.coordinate_to_cell_key((tbl.cursor_row, 0)).row_key.value
            except Exception:
                return None
            if key and key[0] == 's':
                i = int(key[1:])
                if 0 <= i < len(self._search_results):
                    return ('search', i, self._search_results[i])
            return None     # an artist / album row, not a track
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
        # Only handle the main results table. A modal's DataTable (e.g. the artist page's
        # 'artist-table', keyed 'r8') bubbles its RowSelected up to the app too; handling it
        # here would int() a non-numeric key and crash.
        if event.data_table.id == 'search-table':
            key = event.row_key.value
            if not key:
                return
            if key.startswith('A:'):        # artist row → open the artist page
                self._open_artist_channel(key[2:])
            elif key.startswith('B:'):      # album row → load the album
                self._open_album(key[2:])
            else:
                i = int(key[1:])
                self._debounce_play(lambda: self._play_search_hit(i))
            return
        if event.data_table.id != 'results-table':
            return
        key = event.row_key.value
        if key is None:
            return
        if self.view_mode == 'queue':
            qi = int(key[1:])
            if 0 <= qi < len(self._queue):
                self._debounce_play(lambda: self._play_queue_item(qi))
        else:
            idx = int(key)
            if idx < len(self._results):
                # Keep the whole loaded list as the queue and point the index at
                # the chosen track, so jumping behaves like auto-advance — the
                # n/total counter stays stable instead of resetting to 1.
                def _go(i=idx):
                    self._set_queue(self._results)
                    self._queue_idx = i
                    self._play_queue_item(i)
                self._debounce_play(_go)

    def _set_queue(self, tracks) -> None:
        """Replace the queue with a list in its own order. That order is not
        shuffled, so the flag goes off with it — the footer used to keep
        saying 'shuffle' over a queue that played straight through."""
        self._queue = list(tracks)
        if self.shuffle:
            self.shuffle = False
            self._update_footer()

    def _debounce_play(self, fn) -> None:
        """Coalesce rapid selections (misclicks) so only the final pick actually loads — a
        wrong pick's extraction never starts (starting it can wedge the fetch pathway)."""
        if self._play_timer is not None:
            self._play_timer.stop()
        self._play_timer = self.set_timer(0.15, fn)

    def _open_album(self, browse_id: str) -> None:
        """Load an album (browseId) into results+queue and play it."""
        name = next((a['name'] for a in self._search_albums
                     if a.get('browseId') == browse_id), 'Album')
        self._set_status(f'Loading album "{name}"…')

        def _run():
            try:
                tracks = youtube.ytm_album(browse_id)
            except Exception as exc:
                self.call_from_thread(self._set_status, f'Album error: {exc}')
                return
            if tracks:
                self.call_from_thread(self._start_track_list, tracks, 0, name)
            else:
                self.call_from_thread(self._set_status, 'Empty album.')

        threading.Thread(target=_run, daemon=True).start()

    def _play_queue_item(self, idx: int, start: float = 0.0) -> None:
        if idx < 0 or idx >= len(self._queue):
            return
        track = self._queue[idx]
        # A premium retry or the gapless prefetch parks a direct googlevideo
        # stream here (consumed once, never stored in track['url'] — direct URLs
        # expire in hours and must not leak into recent/sessions/playlists).
        direct_url = track.pop('_direct_url', None)
        direct_ts = track.pop('_direct_ts', None)
        if direct_url and direct_ts and time.monotonic() - direct_ts > 1800:
            direct_url = None   # stale pre-resolve — let mpv extract fresh
        self._prefetch_gen = getattr(self, '_prefetch_gen', 0) + 1
        self._queue_idx = idx
        self.now_playing = f'{track["title"]}  —  {track["uploader"]}'
        self._lib.add_recent(track)
        self._loading_since = time.monotonic()      # for the load watchdog in _poll_player
        # Starts a fresh play for the play COUNT (seconds accrue per poll anyway).
        # Without this a repeat-one loop would only ever count as a single play.
        self._stats.begin_track(track)
        self.is_paused = False        # play un-pauses; lets the wave start at once
        self._set_status('Loading…')
        self._render_table()
        if self._search_open:
            self._render_search()
        self._update_footer()
        self._sync_animation()
        self._sync_art_panel()      # swap the cover now, not on the next poll tick
        self._last_bar_sig = None   # and the bar: it lagged the pick by up to 1s
        self._update_player_bar()
        # The OS now-playing panel wants the cover too, and it's visible even
        # when the side panel isn't (narrow terminal, or no Pillow) — so the
        # download is driven by playback, not by the panel.
        if self._mediakeys is not None and not artwork.cached(track):
            self._fetch_art(track)
        url = direct_url or track['url']

        def _run():
            try:
                self._player.play(url, start=start)
                self.call_from_thread(self._set_status, 'Playing')
            except Exception as exc:
                self.call_from_thread(self._set_status, f'Playback error: {exc}')

        threading.Thread(target=_run, daemon=True).start()
        self._prefetch_next()

    def _prefetch_next(self) -> None:
        """Gapless: pre-resolve the NEXT queue track's direct stream URL in the
        background, so auto-advance hands mpv an already-extracted googlevideo
        URL instead of a watch URL (skips the ~2-4s yt-dlp extraction). The URL
        rides the one-shot `_direct_url` key — consumed by _play_queue_item,
        stripped by library._sanitize_tracks, expired after 30 min — so it can
        never be persisted or go stale mid-session."""
        if self.repeat == 'one' or not self._queue:
            return
        nxt = self._queue_idx + 1
        if nxt >= len(self._queue):
            if self.repeat != 'all':
                return
            nxt = 0
        if nxt == self._queue_idx:
            return
        track = self._queue[nxt]
        url = track.get('url') or ''
        if not url.startswith('http'):
            return          # offline/local file — nothing to pre-resolve
        if track.get('_direct_url') and \
                time.monotonic() - track.get('_direct_ts', 0) < 1500:
            return          # already prefetched and still fresh
        gen = self._prefetch_gen

        def _run():
            res = youtube.resolve_stream(track.get('id') or url)
            # Drop the result if the queue was replaced while we resolved (the
            # dict we'd write to is orphaned anyway — this just avoids noise).
            if res is None or gen != self._prefetch_gen:
                return
            track['_direct_url'] = res[1]
            track['_direct_ts'] = time.monotonic()

        threading.Thread(target=_run, daemon=True).start()

    def _on_track_end(self) -> None:
        """Called by the player when a track finishes (natural eof/error)."""
        # Cascade guard: a track that ends WITHOUT EVER PRODUCING AUDIO failed to
        # load (extraction error), it didn't finish. Advancing on those skips the
        # whole queue silently, so stop after a few in a row. The signal is
        # _loading_since — cleared by _poll_player only once position/duration
        # appear. (A <2s time window was used before, but a failing mpv+yt-dlp
        # load takes ~3s to error, so real failures looked like normal track
        # ends: no premium retry, counter reset, endless skipping.)
        never_played = self._loading_since is not None
        if never_played:
            # A track that never starts may be Music-Premium-gated (anonymous
            # extraction rejected). If signed in, retry it once with account cookies.
            if self._maybe_premium_retry():
                return
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

    def _maybe_premium_retry(self) -> bool:
        """Re-resolve the current track with the signed-in account's cookies and
        replay its direct stream (Music-Premium-only tracks reject the default
        anonymous extraction). One attempt per track; returns True when a retry
        was started, so the caller must not auto-advance. Runs the network work
        in a daemon thread — never blocks the player callback thread."""
        if not (0 <= self._queue_idx < len(self._queue)):
            return False
        track = self._queue[self._queue_idx]
        vid = track.get('id')
        if not vid or self._premium_retry_id == vid:
            return False
        if youtube._account_cookie_opts() is None:   # signed out — nothing to retry with
            return False
        self._premium_retry_id = vid
        idx = self._queue_idx
        self.call_from_thread(self._set_status,
                              'Track needs your account — retrying signed in…')

        def _run():
            res = youtube.resolve_premium_stream(vid)
            if res is not None:
                # Direct googlevideo URL: mpv plays it without re-extracting
                # anonymously. Expires after a few hours — handed over out-of-band
                # (_direct_url, consumed once) so it can never be persisted.
                track['_direct_url'] = res[1]
                track['_direct_ts'] = time.monotonic()
                self.call_from_thread(self._play_queue_item, idx)
            else:
                self.call_from_thread(
                    self._set_status,
                    f'Couldn\'t play "{track["title"]}" even signed in — skipping.')
                self._on_track_end()   # retry id is set → falls through to advance

        threading.Thread(target=_run, daemon=True).start()
        return True

    # ── mpv/IPC recovery (stale socket after idle/sleep) ────────────────────

    def _maybe_recover(self) -> None:
        """Start ONE mpv/IPC recovery when the socket has died while a track
        should be playing. UI-thread only (Textual is single-threaded), so the
        _recovering check-and-set is atomic; a 15s cooldown bounds retries."""
        if self._recovering or not self.now_playing:
            return
        if self._player.ipc_healthy():
            return
        if not (0 <= self._queue_idx < len(self._queue)):
            return
        if time.monotonic() - self._last_recover_ts < 15:
            return
        self._recovering = True
        self._last_recover_ts = time.monotonic()
        idx = self._queue_idx
        pos = max(0.0, self.position)
        self._set_status('Reconnecting to audio…')
        threading.Thread(target=self._recover_worker, args=(idx, pos),
                         daemon=True).start()

    def _recover_worker(self, idx, pos) -> None:
        # Tear down the stale mpv+IPC (blocking kill) off the UI thread, then
        # reload the current track at its position — _play_queue_item → play →
        # _ensure_mpv_running spawns a fresh mpv + fresh _MpvIPC.
        try:
            self._player.quit()
        except Exception:
            pass

        def _finish():
            self._recovering = False
            self._play_queue_item(idx, start=pos)

        try:
            self.call_from_thread(_finish)
        except Exception:
            self._recovering = False

    def _begin_app_nap_suppression(self) -> None:
        """macOS: stop App Nap from throttling our event/IPC loop while idle —
        that throttling is what stales the mpv socket after the app sits idle.
        No-op off macOS or without pyobjc (the media-keys macOS extra); the
        token is held on self so it isn't GC'd (releasing re-enables App Nap)."""
        if sys.platform != 'darwin':
            return
        try:
            from Foundation import (NSProcessInfo,
                                    NSActivityUserInitiatedAllowingIdleSystemSleep)
        except Exception:
            return
        try:
            self._app_nap_token = NSProcessInfo.processInfo() \
                .beginActivityWithOptions_reason_(
                    NSActivityUserInitiatedAllowingIdleSystemSleep,
                    'ytm-tui audio playback')
        except Exception:
            self._app_nap_token = None

    # ── Player polling ────────────────────────────────────────────────────

    def _poll_player(self) -> None:
        self.position  = self._player.get_position()
        self.duration  = self._player.get_duration()
        self.is_paused = self._player.is_paused()
        # Backstop: a socket that died with no key pressed (passive stall after
        # sleep/App Nap) still self-heals within ~1s. ipc_healthy() reads a bool
        # (no IPC send), so the poll stays non-blocking on the UI thread.
        if (self.now_playing and not self.is_paused
                and not self._player.ipc_healthy()):
            self._maybe_recover()
            return
        # Listen-time accumulator: count only real forward audio progress on the
        # SAME track — pauses/buffering (position frozen), seeks (delta outside
        # 0..2s for a 1s poll) and track changes all contribute nothing.
        if self.now_playing and not self.is_paused:
            prev = self._stats_last
            if prev is not None and prev[0] == self._queue_idx:
                delta = self.position - prev[1]
                if 0 < delta <= 2.0:
                    track = (self._queue[self._queue_idx]
                             if 0 <= self._queue_idx < len(self._queue) else None)
                    self._stats.add(delta, track=track)
            self._stats_last = (self._queue_idx, self.position)
        else:
            self._stats_last = None
        # Load watchdog: once playback really starts (position/duration known), clear it;
        # if nothing has started within the timeout the fetch is stuck (e.g. a wedged
        # backend) — surface a retry and recover mpv so the next pick works without an app
        # restart. Network timeouts (player.py) normally error out first; this is the backstop.
        if self._loading_since is not None and self.now_playing:
            if self.duration > 0 or self.position > 0:
                self._loading_since = None
                # Real playback started — allow a future premium retry for this
                # track (e.g. its cached direct URL expires hours later).
                self._premium_retry_id = None
            elif time.monotonic() - self._loading_since > 25:
                self._loading_since = None
                title = (self._queue[self._queue_idx]['title']
                         if 0 <= self._queue_idx < len(self._queue) else 'track')
                self._set_status(f'Couldn\'t load "{title}" — press Enter to retry.')
                threading.Thread(target=self._player.quit, daemon=True).start()
        # Start/stop the color-wave to match play/pause/stop state (cheap check).
        self._sync_animation()
        # Keep the cover panel on the current track (no-op unless something moved).
        self._sync_art_panel()
        self._fit_columns()         # no-op unless a pane changed width
        if time.strftime('%H:%M') != self._clock:
            self._update_topbar()
        # Only redraw the player bar when something visible actually changed.
        # While paused or idle the position is frozen, so this skips the redraw
        # (and the repaint) entirely — no work happens on most ticks.
        sig = (int(self.position), int(self.duration), self.is_paused,
               self.now_playing, self.volume, self._queue_idx, len(self._queue))
        if sig == self._last_bar_sig:
            return
        self._last_bar_sig = sig
        self._update_player_bar()
        # Feed the OS now-playing panel (media keys backend); cheap + coalescing.
        if self._mediakeys is not None:
            if self.now_playing and 0 <= self._queue_idx < len(self._queue):
                t = self._queue[self._queue_idx]
                # Only a cover already on disk — the panel picks it up on the
                # next tick once _fetch_art lands, and nothing blocks here.
                self._mediakeys.set_now_playing(
                    t.get('title', ''), t.get('uploader', ''),
                    self.duration, self.position, not self.is_paused,
                    artwork.cached(t))
            else:
                self._mediakeys.set_now_playing('', '', 0, 0, False, '')

    def _update_player_bar(self) -> None:
        pos = self.position
        dur = self.duration
        qpos = (f'{self._queue_idx + 1}/{len(self._queue)}'
                if self._queue and self._queue_idx >= 0 else '0/0')
        pause_icon = '‖' if self.is_paused else '▸'
        controls = (f'◂◂  {pause_icon}  ▸▸   Vol: {self.volume}%   '
                    f'Queue {qpos}   {_fmt(pos)} / {_fmt(dur)}')
        try:
            # As wide as the row it sits in (50 until the layout has a size).
            bar = _bar(pos, dur, width=max(
                20, self.query_one('#progress-row', Static).size.width or 50))
        except NoMatches:
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

    # ── Cover art panel ─────────────────────────────────────────────────────
    def on_resize(self, event) -> None:
        # A blank row between the blocks, once there are rows to spare.
        self.set_class(self.size.height >= 34, '-tall')
        self._sync_art_panel()
        self.call_after_refresh(self._fit_columns)

    def on_data_table_row_highlighted(self, event) -> None:
        """Track what the cursor sits on, for the lower half of the art panel."""
        tid = getattr(event.data_table, 'id', '')
        if tid not in ('results-table', 'search-table'):
            return
        key = getattr(event.row_key, 'value', None)
        track = self._track_for_row(key, search=(tid == 'search-table'))
        if track is not self._cursor_track:
            self._cursor_track = track
            self._cursor_since = time.monotonic()
            self._sync_art_panel()

    def _track_for_row(self, key, search=False):
        """The track dict behind a table row key, or None for the
        artist/album entity rows (A:/B:) that aren't tracks at all."""
        if not key or key[:2] in ('A:', 'B:'):
            return None
        try:
            if search:
                i = int(key[1:])
                return (self._search_results[i]
                        if 0 <= i < len(self._search_results) else None)
            if self.view_mode == 'queue':
                i = int(key[1:])
                return self._queue[i] if 0 <= i < len(self._queue) else None
            i = int(key)
        except (ValueError, TypeError):
            return None
        return self._results[i] if 0 <= i < len(self._results) else None

    def _sync_art_panel(self) -> None:
        """Fill the column right of the results: the playing track's cover in
        the top two thirds, whatever the cursor is on in the bottom third. The
        panel only exists while the terminal is wide enough for the table to
        keep its full width, and everything is keyed on a signature, so the
        1 Hz poll does no work while nothing has moved."""
        try:
            panel = self.query_one('#art-panel', Vertical)
        except NoMatches:
            return
        playing = (self._queue[self._queue_idx]
                   if self.now_playing and 0 <= self._queue_idx < len(self._queue)
                   else None)
        cursor = self._cursor_track
        room = self.size.width - ART_TABLE_COLS
        if (room < ART_MIN_COLS or not artwork.available()
                or (playing is None and cursor is None)):
            if panel.has_class('visible'):
                panel.remove_class('visible')
                self.call_after_refresh(self._fit_columns)
            self._art_sig = None
            return
        cols = min(room, ART_MAX_COLS)
        if not panel.has_class('visible'):
            panel.styles.width = cols
            panel.add_class('visible')
            self.call_after_refresh(self._fit_columns)   # the lists just narrowed
            return      # geometry lands on the next layout; fill in on the next tick
        panel.styles.width = cols
        img = self.query_one('#art-image', Static)
        # Measured, not computed: padding comes from the CSS above, and a cover
        # one cell too wide would wrap — a wrapped row shears the whole picture.
        # A fresh resize lands here with last frame's width; the signature
        # catches that on the next tick.
        art_cols = img.size.width
        # Caption rows come off each section: 6 up top (title, artist, album,
        # facts, your own line, and the margin above them), 2 below.
        now_rows = max(0, self.query_one('#art-now', Vertical).size.height - 6)
        cur_rows = max(0, self.query_one('#art-cursor', Vertical).size.height - 2)
        if art_cols < 2:
            return      # layout hasn't settled yet — try again on the next tick
        style = self._config.art_style
        details = self._details.get(_art_key(playing)) if playing else None
        # Liking with `l` mid-track must redraw the heart, so it's in the key.
        liked = bool(playing) and self._lib.is_liked(playing)
        sig = (_art_key(playing), _art_key(cursor), art_cols,
               now_rows, cur_rows, style, bool(details), liked)
        if sig == self._art_sig:
            return
        self._art_sig = sig
        self._draw_cover(playing, '#art-image', '#art-title', '#art-artist',
                         art_cols, now_rows, style)
        self._draw_cover(cursor, '#art-cursor-image', '#art-cursor-title', None,
                         art_cols, cur_rows, style)
        self._draw_details(playing, details, art_cols)

    def _draw_details(self, track, details, cols) -> None:
        """Under the playing track: the album, a 'year · length · plays' line,
        and your own line (your listens across every device, and a heart if
        you liked it). `details` is None until the network lookup lands — those
        lines stay empty until then, and the lookup is fired here. Your line is
        local and shows at once."""
        album = self.query_one('#art-album', Static)
        facts = self.query_one('#art-facts', Static)
        you = self.query_one('#art-you', Static)
        if track is None:
            album.update('')
            facts.update('')
            you.update('')
            return
        you.update(_ellipsis(self._you_line(track, details or {}), cols))
        if details is None:
            self._fetch_details(track)
            details = {}
        album.update(_ellipsis(details.get('album') or '', cols))
        bits = []
        if details.get('year'):
            bits.append(details['year'])
        if track.get('duration'):
            bits.append(_fmt(track['duration']))
        if details.get('views'):
            bits.append(f'{_compact(details["views"])} plays')
        facts.update(_ellipsis('  ·  '.join(bits), cols))

    def _you_line(self, track, details) -> str:
        """'♥  you · 37 plays · 2h 14m' — summed over every stats key with
        this video id, because the same track can be filed under slightly
        different titles by different clients (desktop vs iOS metadata)."""
        vid = track.get('id') or ''
        plays = secs = 0
        if vid:
            try:
                recs = self._stats.merged_records(
                    'tracks', self._config.stats_device_id)
            except Exception:
                recs = {}
            prefix = f'{vid}|'
            for key, rec in recs.items():
                if key.startswith(prefix):
                    plays += int(rec.get('n') or 0)
                    secs += float(rec.get('s') or 0)
        # Liked in the app OR on the YouTube account — either is your heart.
        heart = self._lib.is_liked(track) or details.get('liked')
        bits = ['you']
        if plays:
            bits.append(f'{plays} play' + ('' if plays == 1 else 's'))
        if secs >= 60:
            bits.append(_listened(secs))
        if len(bits) == 1:
            bits.append('first listen')
        if details.get('saved'):
            bits.append('in library')
        return ('♥  ' if heart else '') + '  ·  '.join(bits)

    def _fetch_details(self, track) -> None:
        """Look up album / release year / play count once per track, off the UI
        thread. A track with nothing to find caches an empty dict, so a local
        file or a dead id isn't retried every time it comes up."""
        key = _art_key(track)
        vid = track.get('id') or ''
        if not key or key in self._details or key in self._details_fetching:
            return
        if not vid or not (track.get('url') or '').startswith('http'):
            self._details[key] = {}
            return
        self._details_fetching.add(key)

        def _run():
            try:
                got = youtube.ytm_track_details(vid)
            except Exception:
                got = {}
            self._details_fetching.discard(key)
            self._details[key] = got

            def _apply():
                self._art_sig = None
                self._sync_art_panel()

            try:
                self.call_from_thread(_apply)
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()

    def _draw_cover(self, track, img_id, title_id, artist_id, cols, rows,
                    style) -> None:
        img = self.query_one(img_id, Static)
        title = self.query_one(title_id, Static)
        artist = self.query_one(artist_id, Static) if artist_id else None
        if track is None:
            img.update('')
            title.update('')
            if artist is not None:
                artist.update('')
            return
        title.update(_ellipsis(track.get('title') or '', cols))
        if artist is not None:
            artist.update(_ellipsis(track.get('uploader') or '', cols))
        if rows < 2:
            img.update('')
            return
        path = artwork.cached(track)
        if not path:
            # Scrolling shouldn't fire a download per row: the cursor has to
            # settle first. The playing track is never debounced.
            if (track is not self._cursor_track
                    or time.monotonic() - self._cursor_since > 0.3):
                self._fetch_art(track)
            else:
                self._art_sig = None        # come back for it on the next tick
            return      # keep the previous cover up rather than blinking to empty
        art = artwork.render(path, cols, rows, style)
        img.update(art if art is not None else '')

    def _fetch_art(self, track) -> None:
        """Download one cover in the background, then redraw. One flight per
        track — a failed fetch isn't retried until the track comes up again."""
        key = _art_key(track)
        if not key or key in self._art_fetching:
            return
        self._art_fetching.add(key)

        def _run():
            got = artwork.fetch(track)
            self._art_fetching.discard(key)
            if got:
                # Force a redraw: the signature already reflects this track.
                self._art_sig = None
                self.call_from_thread(self._sync_art_panel)

        threading.Thread(target=_run, daemon=True).start()

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
        # Per-theme spinner frames in the ♪ slot (stepped slower than the wave so it
        # reads as a pulse, not a flicker); colored by the same wave.
        frames = ANIMATED_GLYPHS.get(self.theme)
        head = (frames[(f // 2) % len(frames)] if frames else '♪') + '  '
        # Now-playing bar (single height-1 widget). Catch everything — a timer
        # callback must never raise (that crashes the app).
        try:
            self.query_one('#now-playing', Static).update(
                _wave_text(head + self.now_playing, palette, f))
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
        if getattr(self, '_stats_syncing', False):
            left.append('    ')
            left.append('⟳ sync', style=f'bold {self._accent()}')
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
                inp.placeholder = f'Local folder path ({_EG_FOLDER})…'
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
        self._set_paused(not self.is_paused)

    def _media_play(self) -> None:
        """OS media key / Control Center 'play' — resume only, never a toggle."""
        if self.is_paused:
            self._set_paused(False)

    def _media_pause(self) -> None:
        """OS media key / Control Center 'pause' — pause only, never a toggle.

        The OS sends this by itself when the audio device goes away (headphones
        unplugged, Bluetooth off). Treating it as a toggle made an already-paused
        track start playing out loud through the built-in speakers."""
        if not self.is_paused:
            self._set_paused(True)

    def _set_paused(self, want_paused: bool) -> None:
        if not self.now_playing:
            return
        # Optimistic: flip the bar instantly so a keypress never waits on a
        # stalled IPC socket. The mpv round-trip runs off the UI thread; the
        # optimistic value is authoritative (Player.pause/resume set _paused
        # before the blocking set_property, and _poll_player re-reads it 1/s).
        self.is_paused = want_paused
        self._last_bar_sig = None      # force an immediate bar redraw
        self._update_player_bar()
        self._sync_animation()

        def _run():
            try:
                self._player.pause() if want_paused else self._player.resume()
            finally:
                if not self._player.ipc_healthy():
                    self.call_from_thread(self._maybe_recover)

        threading.Thread(target=_run, daemon=True).start()

    def action_next_track(self) -> None:
        nxt = self._queue_idx + 1
        if nxt >= len(self._queue):
            if self.repeat == 'all' and self._queue:
                nxt = 0
            else:
                return
        self._play_queue_item(nxt)

    def action_prev_track(self) -> None:
        """Previous-track semantics like every player: restart the current
        track when it's more than a few seconds in, else go back one."""
        if not self._queue or self._queue_idx < 0:
            return
        if self.position > 3 or self._queue_idx == 0:
            self._play_queue_item(self._queue_idx)
        else:
            self._play_queue_item(self._queue_idx - 1)

    def action_stop(self) -> None:
        # Clear the UI instantly; the blocking IPC 'stop' runs off-thread. No
        # recovery on stop — the user wants silence, and the next play rebuilds
        # mpv via _ensure_mpv_running if the socket had died.
        self.now_playing = ''
        self.is_paused = False
        self._set_status('Stopped')
        self._render_table()
        self._update_footer()
        self._sync_animation()
        threading.Thread(target=self._player.stop, daemon=True).start()

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
        # By position, not identity: the same track can be queued twice, and
        # an identity test dropped every copy of the one that's playing.
        rest = [t for i, t in enumerate(self._queue)
                if cur is None or i != self._queue_idx]
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

    def _target_track(self):
        """The track the L/R/A actions operate on: highlighted row, else now-playing."""
        hit = self._highlighted_track()
        if hit:
            return hit[2]
        if 0 <= self._queue_idx < len(self._queue):
            return self._queue[self._queue_idx]
        return None

    def action_lyrics(self) -> None:
        track = self._target_track()
        if not track or not track.get('id'):
            self._set_status('No track for lyrics.')
            return
        self._set_status(f'Fetching lyrics for "{track["title"]}"…')

        def _run():
            data = youtube.ytm_lyrics(track['id'])
            if not data:
                self.call_from_thread(self._set_status, 'No lyrics available for this track.')
                return
            self.call_from_thread(
                self.push_screen, LyricsScreen(track['title'], data, track['id']))
            self.call_from_thread(self._set_status, 'Playing' if self.now_playing else 'Ready')

        threading.Thread(target=_run, daemon=True).start()

    # ── Queue reorder (K/J or Shift+↑/↓) ───────────────────────────────────

    def action_move_track_up(self) -> None:
        self._move_track(-1)

    def action_move_track_down(self) -> None:
        self._move_track(+1)

    def _move_track(self, delta: int) -> None:
        """Move the highlighted queue track up/down one slot. Queue view only — the
        library view is a browse list, not the play order."""
        if self.view_mode != 'queue':
            self._set_status('Open the queue (Q) to reorder it.')
            return
        hit = self._highlighted_track()
        if not hit or hit[0] != 'queue':
            self._set_status('No queue track highlighted.')
            return
        qi = hit[1]
        tj = qi + delta
        if not (0 <= tj < len(self._queue)):
            return
        q = self._queue
        q[qi], q[tj] = q[tj], q[qi]
        # The playing pointer follows its song so auto-advance stays correct.
        if self._queue_idx == qi:
            self._queue_idx = tj
        elif self._queue_idx == tj:
            self._queue_idx = qi
        self._render_table()
        try:
            self.query_one('#results-table', DataTable).move_cursor(row=tj)
        except NoMatches:
            pass
        self._update_footer()
        self._set_status(f'Moved "{q[tj]["title"]}" to {tj + 1}/{len(q)}')

    def action_radio(self) -> None:
        track = self._target_track()
        if not track or not track.get('id'):
            self._set_status('No track to start radio from.')
            return
        self._set_status(f'∞ Building radio from "{track["title"]}"…')

        def _apply(tracks):
            playing = (self._queue[self._queue_idx]
                       if (self.now_playing and 0 <= self._queue_idx < len(self._queue))
                       else None)
            if playing is not None and playing.get('id') == track['id']:
                # The seed is on the air: swap the queue underneath it and keep the
                # audio going — never restart the song the user is listening to.
                mix = [t for t in tracks if t.get('id') != track['id']]
                mix.insert(0, playing)
                self._new_load()
                self._open_list(f'∞ Radio: {track["title"]}', mix)
                self._set_queue(mix)
                self._queue_idx = 0
                self._set_status(f'∞ Radio: {track["title"]} — queue updated')
            else:
                self._start_track_list(tracks, 0, f'∞ Radio: {track["title"]}')

        def _run():
            try:
                tracks = youtube.ytm_radio(track['id'])
            except Exception as exc:
                self.call_from_thread(self._set_status, f'Radio error: {exc}')
                return
            if not tracks:
                self.call_from_thread(self._set_status, 'No radio available for this track.')
                return
            self.call_from_thread(_apply, tracks)

        threading.Thread(target=_run, daemon=True).start()

    def action_artist(self) -> None:
        # Prefer the top artist from the last search; else the current/highlighted track's
        # uploader (looked up by name).
        if self._search_artists:
            self._open_artist_channel(self._search_artists[0]['channelId'])
            return
        track = self._target_track()
        name = (track or {}).get('uploader') or ''
        name = name.split(',')[0].strip()
        if not name:
            self._set_status('No artist to open.')
            return
        self._set_status(f'Finding artist "{name}"…')

        def _run():
            try:
                ent = youtube.ytm_search_entities(name)
                arts = ent.get('artists') or []
            except Exception:
                arts = []
            if not arts:
                self.call_from_thread(self._set_status, f'No artist page for "{name}".')
                return
            self.call_from_thread(self._open_artist_channel, arts[0]['channelId'])

        threading.Thread(target=_run, daemon=True).start()

    def _open_artist_channel(self, channel_id: str) -> None:
        self._set_status('Loading artist…')

        def _run():
            try:
                page = youtube.ytm_artist(channel_id)
            except Exception as exc:
                self.call_from_thread(self._set_status, f'Artist error: {exc}')
                return
            self.call_from_thread(self.push_screen, ArtistScreen(page), self._on_artist_result)
            self.call_from_thread(self._set_status, page.get('name') or 'Artist')

        threading.Thread(target=_run, daemon=True).start()

    def _on_artist_result(self, result) -> None:
        if not result:
            return
        kind = result[0]
        if kind == 'play':
            _, tracks, idx = result
            self._start_track_list(tracks, idx, result[3] if len(result) > 3 else 'Artist')
        elif kind == 'album':
            _, browse_id, name = result
            self._set_status(f'Loading album "{name}"…')

            def _run():
                try:
                    tracks = youtube.ytm_album(browse_id)
                except Exception as exc:
                    self.call_from_thread(self._set_status, f'Album error: {exc}')
                    return
                if tracks:
                    self.call_from_thread(self._start_track_list, tracks, 0, name)
                else:
                    self.call_from_thread(self._set_status, 'Empty album.')

            threading.Thread(target=_run, daemon=True).start()

    def _start_track_list(self, tracks, idx=0, label='') -> None:
        """Load a track list into results+queue and start playing at idx."""
        self._new_load()        # a playlist still in flight must not replace this
        self._close_search()    # an album or artist picked there replaces the list
        self._open_list(label or 'List', tracks)
        self._set_queue(tracks)
        self._queue_idx = idx
        self._play_queue_item(idx)
        if label:
            self._set_status(label)

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
        trail = ([e['label'] for e in self._trail], self._trail_root,
                 self._trail_pos)
        self.push_screen(
            HomeScreen(self._lib, self._stats, self._config, trail=trail),
            self._on_home_result)

    # Keys that act on the listening view's tables or inputs. The home map
    # is a screen on top of them, so there they would act on rows nobody can
    # see (or put the focus on a hidden input).
    _LIST_ACTIONS = frozenset((
        'focus_search', 'filter', 'add_queue', 'play_next', 'toggle_view',
        'move_track_up', 'move_track_down', 'like', 'lyrics', 'artist',
        'radio', 'save_playlist', 'home', 'clear_filter',
    ))

    def check_action(self, action, parameters):
        if action in self._LIST_ACTIONS and isinstance(self.screen, HomeScreen):
            return False
        return True

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
                self._set_status('Offline mode — type a folder path and press Enter')
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
        vol = self.volume
        if save:
            self._config.update(volume=vol)
            self._schedule_config_flush()
        self._update_footer()      # footer shows volume — reflect it now
        # The mpv set_property round-trip runs off the UI thread (blocks on a
        # stale socket otherwise). Recover if it reveals a dead IPC mid-playback.
        def _run():
            try:
                self._player.set_volume(vol)
            finally:
                if self.now_playing and not self._player.ipc_healthy():
                    self.call_from_thread(self._maybe_recover)
        threading.Thread(target=_run, daemon=True).start()

    def action_seek_back(self) -> None:
        self._seek(-10)

    def action_seek_fwd(self) -> None:
        self._seek(10)

    def _seek(self, delta) -> None:
        # mpv corrects self.position via observe_property on the next poll, so
        # no optimistic nudge is needed — just don't block the UI thread.
        if not self.now_playing:
            return
        def _run():
            try:
                self._player.seek(delta)
            finally:
                if not self._player.ipc_healthy():
                    self.call_from_thread(self._maybe_recover)
        threading.Thread(target=_run, daemon=True).start()

    def action_show_keys(self) -> None:
        self.push_screen(KeybindingsScreen())

    def action_changelog(self) -> None:
        self.push_screen(ChangelogScreen())

    def action_settings(self) -> None:
        def _after(result):
            if result is None:
                return
            device = result.get('device_name', '').strip()
            if device and device != self._config.stats_device_name:
                self._config.stats_device_name = device
            token = result.get('stats_token', '').strip()
            token_changed = token != self._config.stats_token
            if token_changed:
                self._config.stats_token = token
            self._set_status('Sync settings saved')
            # A new token gets validated right away (result lands in the
            # status line: 'connected ✓' or 'token rejected').
            if token_changed and token:
                self._stats_sync_maybe(announce=True)

        self.push_screen(
            SettingsScreen(self._config.stats_token,
                           self._config.stats_device_name,
                           stats=self._stats, cfg=self._config),
            _after,
        )
        # Freshen the panel's graph with other devices' latest numbers
        # (throttled no-op when a sync ran in the last few minutes).
        self._stats_sync_maybe()

    # ── YouTube account ─────────────────────────────────────────────────────

    def action_account(self) -> None:
        def _after(result):
            if result is None:
                return
            method = result.get('method', 'none')
            cookies = result.get('cookies_file', self._config.auth_cookies_file)
            browser = result.get('browser', '')
            profile = result.get('profile', '')
            # Persist the chosen method + its inputs and re-wire the client.
            self._config.auth_method = method
            # Auth cookies feed ytmusicapi ONLY — deliberately NOT the player. An
            # authenticated YouTube session breaks yt-dlp streaming (SABR-only
            # formats). Streaming cookies are a separate setting (Settings, `s`).
            if cookies != self._config.auth_cookies_file:
                self._config.auth_cookies_file = cookies
            if method == 'browser':
                self._config.auth_browser = browser
                self._config.auth_browser_profile = profile
            # Persist the signed-in display name for the footer (cleared on sign-out).
            self._config.account_name = (result.get('account_name', '')
                                         if method != 'none' else '')
            youtube.configure_auth(method, cookies,
                                   browser=browser, profile=profile)
            self._update_footer()
            # The modal was dismissed on the UI thread (no worker-thread dismiss → input
            # is NOT wedged). Confirm the live session in the background — same daemon
            # path boot uses — which fills in the account name on success, or alerts on a
            # confirmed logout. Never validate-then-dismiss from a worker thread (gotcha).
            if method in ('cookies', 'browser'):
                self._set_status('Signing in…')
                threading.Thread(target=self._verify_account,
                                 kwargs={'signing_in': True}, daemon=True).start()
                return
            self._set_status('YouTube auth: ' + youtube.auth_status()
                             + (' — personalized' if youtube.is_authenticated() else ''))

        def _set_stream_cookies(path):
            # Player-only cookie file (age-restricted playback), never auth.
            if path != self._config.cookies_file:
                self._config.cookies_file = path
                self._player.cookies_file = path
                self._set_status('Streaming cookies '
                                 + (f'set: {path}' if path else 'cleared'))

        self.push_screen(
            AccountScreen(self._config.auth_method,
                          self._config.auth_cookies_file,
                          self._config.auth_browser,
                          self._config.auth_browser_profile,
                          stream_cookies=self._config.cookies_file,
                          on_stream_cookies=_set_stream_cookies),
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
        """Esc: close the filter if it's open, else the search pane, else
        just hand the focus back to the list."""
        row = self.query_one('#filter-row', Horizontal)
        if not row.has_class('visible'):
            if self._search_open:
                self._close_search()
            else:
                self._focus_list()
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

    def _finalize_quit(self, save_session: bool = True) -> None:
        if save_session:
            self._save_session()
        self._stats.flush()
        # Best-effort final sync (stats + the just-saved session, so another
        # device can resume it): data is already safe on disk, so never hold
        # the quit hostage — 3s max, then exit regardless.
        if self._config.stats_token:
            t = threading.Thread(target=self._stats.sync, args=(
                self._config.stats_token, self._config.stats_device_id,
                self._config.stats_device_name, self._config.stats_gist_id),
                kwargs={'library_export': self._lib.export_sync(
                    device_name=self._config.stats_device_name)},
                daemon=True)
            t.start()
            t.join(3.0)
        try:
            self._config.flush()
        except Exception:
            pass
        if self._mediakeys is not None:
            self._mediakeys.stop()
        if self._app_nap_token is not None:
            try:
                from Foundation import NSProcessInfo
                NSProcessInfo.processInfo().endActivity_(self._app_nap_token)
            except Exception:
                pass
        self._player.quit()
        self.exit()

    def action_quit(self) -> None:
        if self.now_playing:
            # Three-way: both buttons quit — No means "quit, save nothing".
            # Esc (dismiss None) is the only way to stay in the app.
            def _after(choice):
                if choice is None:
                    return
                self._finalize_quit(save_session=bool(choice))
            self.push_screen(
                ConfirmScreen(
                    'Something is playing.\nSave this session for next time?'
                    '\n(Esc stays in the app)',
                    yes_label='Save & quit (y)', no_label='Just quit (n)',
                    cancel=True,
                ),
                _after,
            )
        else:
            self._finalize_quit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'search-close':
            self._close_search()
        elif event.button.id == 'source-btn':
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
