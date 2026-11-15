"""
homemap.py — the home screen's node map.

A pannable canvas: the hub in the middle, one node per library area around it,
the navigation trail chained off the node it started from, and the open node's
contents as a block hanging under it. Everything is drawn into a cell grid and
handed to Textual a line at a time (`render_line`), so a frame costs one pass
over the grid and no layout.

This module knows nothing about the library or the player: the screen feeds it
rows, the trail and an audio level, and asks it what the cursor is on.
"""

import math

from rich.cells import get_character_cell_size
from rich.segment import Segment
from rich.style import Style
from textual.color import Color
from textual.strip import Strip
from textual.widget import Widget

HUB = 'hub'

# id, label, x, y — world cells, hub at (0, 0). A cell is about twice as tall
# as it is wide, so x distances are roughly double the y ones.
NODES = [
    ('search',    'Search',    0, -10),
    ('resume',    'Resume',    -30, -6),
    ('ytmusic',   'YT Music',  30, -6),
    ('recent',    'Recent',    -36, 0),
    ('liked',     'Liked',     36, 0),
    ('playlists', 'Playlists', -30, 6),
    ('foryou',    'For You',   30, 6),
    ('stats',     'Stats',     -12, 10),
    ('create',    'Create',    12, 10),
]
HUB_LABEL = 'YTTUI'
TRAIL_LABEL_MAX = 18
TRAIL_GAP = 4
BLOCK_W = 58

# Style slots (indexes into MapCanvas._styles).
(S_BG, S_F1, S_F2, S_F3, S_F4, S_LINE, S_LINE_ON, S_NODE, S_NODE_SEL, S_HUB,
 S_NODE_DIM, S_ROW, S_ROW_SEL, S_HEAD, S_MUTED, S_HERE) = range(16)

_FIELD_GLYPHS = ' .·:+'


def _cells(text):
    """(char, width) pairs; zero-width marks ride on the char before them."""
    out = []
    for c in text:
        w = get_character_cell_size(c)
        if w == 0 and out:
            out[-1] = (out[-1][0] + c, out[-1][1])
        elif w > 0:
            out.append((c, w))
    return out


def _width(text):
    return sum(w for _, w in _cells(text))


def _clip(text, width):
    """Cut to `width` cells, with an ellipsis when something was cut."""
    if _width(text) <= width:
        return text
    out, used = [], 0
    for c, w in _cells(text):
        if used + w > width - 1:
            break
        out.append(c)
        used += w
    return ''.join(out) + '…'


class MapCanvas(Widget):
    can_focus = True
    DEFAULT_CSS = 'MapCanvas { width: 1fr; height: 1fr; }'

    def __init__(self, **kw):
        super().__init__(**kw)
        self._map_nodes = {nid: (label, x, y) for nid, label, x, y in NODES}
        self._map_nodes[HUB] = (HUB_LABEL, 0, 0)
        self.sel = HUB              # a node id, or ('trail', i)
        self.open_id = None            # node id whose rows are showing
        self.node_rows = {}              # node id -> [{'label', 'payload', 'header'}]
        self.row_idx = 0
        self.trail = []             # labels, oldest first
        self.trail_root = None      # node id the trail hangs off
        self.trail_pos = -1         # which trail entry is the current list
        self.dim_ids = {'create'}       # nodes drawn muted (nothing behind them yet)
        self._lv_hist = [0.0] * 80     # energy per ring, newest at the centre
        self._lv_avg = 0.0
        self._tickn = 0
        self._bgfield = None          # per screen row: [(x, ring)]
        self._bgfield_size = None
        self._frame = None
        self._pal = None
        self._pal_theme = None

    # ── Model ─────────────────────────────────────────────────────────────

    def set_rows(self, node, rows):
        self.node_rows[node] = rows
        if self.open_id == node:
            self.row_idx = self._first_row(rows, min(self.row_idx, max(0, len(rows) - 1)))
        self.redraw()

    def set_trail(self, labels, root, pos):
        self.trail = list(labels)
        self.trail_root = root if root in self._map_nodes else 'search'
        self.trail_pos = pos
        self.redraw()

    @staticmethod
    def _first_row(rows, start=0, step=1):
        """Nearest row at or after `start` (in `step` direction) that can be
        selected; headers and notes can't."""
        i = start
        while 0 <= i < len(rows):
            if rows[i].get('payload') is not None:
                return i
            i += step
        return start

    def current_row(self):
        rows = self.node_rows.get(self.open_id) or []
        if self.open_id and 0 <= self.row_idx < len(rows):
            return rows[self.row_idx]
        return None

    def open_node(self, node):
        self.open_id = node
        self.sel = node
        self.row_idx = self._first_row(self.node_rows.get(node) or [])
        self.redraw()

    def close(self):
        """Close the open block. False when there was none."""
        if self.open_id is None:
            return False
        self.open_id = None
        self.redraw()
        return True

    def select(self, key):
        self.sel = key
        self.redraw()

    def _node_rect(self, nid):
        label, x, y = self._map_nodes[nid]
        w = _width(label) + 4
        return x - w // 2, y - 1, w, 3

    def _trail_rects(self):
        """[(x0, y, w, label)] for each trail entry, chained outward from the
        root node on the side facing away from the hub."""
        if not self.trail or self.trail_root not in self._map_nodes:
            return []
        x0, y0, w, _h = self._node_rect(self.trail_root)
        _label, nx, ny = self._map_nodes[self.trail_root]
        right = nx >= 0
        edge = x0 + w if right else x0
        out = []
        for label in self.trail:
            text = _clip(label, TRAIL_LABEL_MAX)
            bw = _width(text) + 6           # 2 pad each side + the marker
            if right:
                bx = edge + TRAIL_GAP
                edge = bx + bw
            else:
                bx = edge - TRAIL_GAP - bw
                edge = bx
            out.append((bx, ny - 1, bw, text))
        return out

    def _targets(self):
        out = [(nid, x, y) for nid, (_l, x, y) in self._map_nodes.items()]
        for i, (bx, by, bw, _t) in enumerate(self._trail_rects()):
            out.append((('trail', i), bx + bw // 2, by + 1))
        return out

    def move(self, dx, dy):
        """Arrow key. Inside an open block ↑/↓ walk its rows and ← closes it;
        on the map the cursor jumps to the nearest node in that direction."""
        if self.open_id is not None:
            rows = self.node_rows.get(self.open_id) or []
            if dy:
                i = self._first_row(rows, self.row_idx + dy, dy)
                if 0 <= i < len(rows) and rows[i].get('payload') is not None:
                    self.row_idx = i
                    self.redraw()
            elif dx < 0:
                self.close()
            return
        targets = self._targets()
        here = next(((x, y) for k, x, y in targets if k == self.sel), (0, 0))
        best, best_score = None, None
        for key, x, y in targets:
            if key == self.sel:
                continue
            ddx, ddy = (x - here[0]) / 2.0, float(y - here[1])
            along = ddx * dx + ddy * dy
            across = abs(ddx * dy) + abs(ddy * dx)
            if along <= 0.5 or across > along * 2.5:
                continue
            score = along + across * 2
            if best_score is None or score < best_score:
                best, best_score = key, score
        if best is not None:
            self.sel = best
            self.redraw()

    def page(self, step):
        if self.open_id is None:
            return
        rows = self.node_rows.get(self.open_id) or []
        i = max(0, min(len(rows) - 1, self.row_idx + step))
        i = self._first_row(rows, i, 1 if step > 0 else -1)
        if 0 <= i < len(rows) and rows[i].get('payload') is not None:
            self.row_idx = i
            self.redraw()

    # ── Animation ─────────────────────────────────────────────────────────

    def tick(self, energy=None):
        """One frame. `energy` is the audio level 0..1, or None when nothing
        is playing — then a slow swell keeps the field from freezing."""
        self._tickn += 1
        if energy is None:
            pulse = 0.16 + 0.14 * math.sin(self._tickn * 0.21)
        else:
            # Lean on the change, not the level: a loud steady passage would
            # otherwise paint the whole field solid.
            self._lv_avg += (energy - self._lv_avg) * 0.08
            pulse = max(0.0, min(1.0, energy * 0.55 + (energy - self._lv_avg) * 3.0))
        self._lv_hist.insert(0, pulse)
        self._lv_hist.pop()
        self.redraw()

    def redraw(self):
        self._frame = None
        self.refresh()

    # ── Colors ────────────────────────────────────────────────────────────

    def _build_styles(self):
        try:
            v = self.app.theme_variables
            bg = Color.parse(v['background'])
            surface = Color.parse(v['surface'])
            panel = Color.parse(v['panel'])
            accent = Color.parse(v['accent'])
            fg = Color.parse(v['foreground'])
            if any(c.ansi is not None for c in (bg, surface, panel, accent, fg)):
                raise ValueError('ansi theme')
        except Exception:
            # ANSI themes have no RGB to blend: fall back to terminal styles.
            d = Style(dim=True)
            rev = Style(reverse=True, bold=True)
            return [Style(), d, d, d, Style(), d, Style(bold=True), Style(),
                    rev, Style(bold=True), d, Style(), rev, Style(bold=True),
                    d, Style(bold=True)]

        def mix(a, b, t):
            return a.blend(b, t).rich_color

        b = bg.rich_color
        muted = mix(bg, fg, 0.55)
        node_bg = mix(bg, fg, 0.10)
        return [
            Style(bgcolor=b),
            Style(color=mix(bg, accent, 0.13), bgcolor=b),
            Style(color=mix(bg, accent, 0.22), bgcolor=b),
            Style(color=mix(bg, accent, 0.34), bgcolor=b),
            Style(color=mix(bg, accent, 0.48), bgcolor=b),
            Style(color=mix(bg, fg, 0.28), bgcolor=b),
            Style(color=accent.rich_color, bgcolor=b),
            Style(color=fg.rich_color, bgcolor=node_bg),
            Style(color=b, bgcolor=accent.rich_color, bold=True),
            Style(color=accent.rich_color, bgcolor=node_bg, bold=True),
            Style(color=muted, bgcolor=mix(bg, fg, 0.05)),
            Style(color=fg.rich_color, bgcolor=surface.rich_color),
            Style(color=b, bgcolor=accent.rich_color, bold=True),
            Style(color=accent.rich_color, bgcolor=surface.rich_color, bold=True),
            Style(color=muted, bgcolor=surface.rich_color),
            Style(color=accent.rich_color, bgcolor=node_bg, bold=True),
        ]

    # ── Drawing ───────────────────────────────────────────────────────────

    def _build_field(self, w, h):
        cx, cy = w / 2.0, h / 2.0
        field = []
        for y in range(h):
            row = []
            for x in range(w):
                # A scatter, not a lattice: a regular one reads as diagonal
                # stripes the moment a ring lights it up.
                if ((x * 73856093) ^ (y * 19349663)) % 6:
                    continue
                ring = int(math.hypot((x - cx) / 2.0, y - cy))
                row.append((x, min(ring, len(self._lv_hist) - 1)))
            field.append(row)
        self._bgfield = field
        self._bgfield_size = (w, h)

    def _block_geometry(self, h):
        """(x0, y0, width, first visible row, visible count) of the open
        block, in world cells."""
        rows = self.node_rows.get(self.open_id) or []
        x0, y0, _w, _h = self._node_rect(self.open_id)
        count = min(len(rows), max(3, min(14, h - 7)))
        first = max(0, min(self.row_idx - count // 2, len(rows) - count))
        return x0, y0 + 3, BLOCK_W, first, count

    def _focus_rect(self, w, h):
        if self.open_id is not None:
            x0, y0, bw, _first, count = self._block_geometry(h)
            nx, ny, _nw, _nh = self._node_rect(self.open_id)
            return min(x0, nx), ny, bw, (y0 - ny) + count + 1
        if isinstance(self.sel, tuple):
            rects = self._trail_rects()
            if self.sel[1] < len(rects):
                bx, by, bw, _t = rects[self.sel[1]]
                return bx, by, bw, 3
        return self._node_rect(self.sel if self.sel in self._map_nodes else HUB)

    def _camera(self, w, h):
        """World→screen offset: hub centred, shifted just enough to bring
        whatever has the cursor fully on screen."""
        ox, oy = w // 2, h // 2
        fx, fy, fw, fh = self._focus_rect(w, h)
        if fx + ox < 2:
            ox = 2 - fx
        elif fx + fw + ox > w - 2:
            ox = max(2 - fx, w - 2 - fx - fw)
        if fy + oy < 1:
            oy = 1 - fy
        elif fy + fh + oy > h - 1:
            oy = max(1 - fy, h - 1 - fy - fh)
        return ox, oy

    def _compose_frame(self):
        w, h = self.size.width, self.size.height
        if w <= 0 or h <= 0:
            self._frame = []
            return
        theme = getattr(self.app, 'theme', None)
        if self._pal is None or theme != self._pal_theme:
            self._pal = self._build_styles()
            self._pal_theme = theme
        if self._bgfield_size != (w, h):
            self._build_field(w, h)

        ch = [[' '] * w for _ in range(h)]
        st = [[S_BG] * w for _ in range(h)]

        # Background: rings of the recent audio level moving out from the
        # centre, over a sparse field of dots that drifts a little.
        hist, t = self._lv_hist, self._tickn
        drift = t // 6
        for y, row in enumerate(self._bgfield):
            crow, srow = ch[y], st[y]
            for x, ring in row:
                lvl = int(hist[ring] * (1.0 - ring / 110.0) * 5.0)
                if lvl <= 0:
                    if ((x * 31 + y * 17) ^ drift) % 9:
                        continue
                    lvl = 1
                elif lvl > 4:
                    lvl = 4
                crow[x] = _FIELD_GLYPHS[lvl]
                srow[x] = lvl          # S_F1..S_F4 are 1..4

        ox, oy = self._camera(w, h)

        def put(wx, wy, text, style):
            y = wy + oy
            if not 0 <= y < h:
                return
            x = wx + ox
            for c, cw in _cells(text):
                if 0 <= x and x + cw <= w:
                    ch[y][x] = c
                    st[y][x] = style
                    if cw == 2:
                        ch[y][x + 1] = ''
                        st[y][x + 1] = style
                x += cw

        def fill(wx, wy, bw, bh, style):
            for r in range(bh):
                put(wx, wy + r, ' ' * bw, style)

        def hline(x1, x2, wy, style):
            if x2 < x1:
                x1, x2 = x2, x1
            put(x1, wy, '─' * (x2 - x1 + 1), style)

        active = self.open_id or (self.sel if self.sel in self._map_nodes else None)
        if isinstance(self.sel, tuple):
            active = self.trail_root

        # Connectors, the active one last so it sits on top.
        order = [n for n in self._map_nodes if n not in (HUB, active)]
        if active and active != HUB:
            order.append(active)
        hx0, _hy0, hw, _hh = self._node_rect(HUB)
        for nid in order:
            _label, nx, ny = self._map_nodes[nid]
            x0, _y0, nw, _nh = self._node_rect(nid)
            style = S_LINE_ON if nid == active else S_LINE
            if ny == 0:
                if nx > 0:
                    hline(hx0 + hw, x0 - 1, 0, style)
                else:
                    hline(x0 + nw, hx0 - 1, 0, style)
                continue
            step = 1 if ny > 0 else -1
            if nx == 0:
                for y in range(2 * step, ny - step, step):
                    put(0, y, '│', style)
                continue
            ex = (3 if abs(nx) >= 20 else 1) * (1 if nx > 0 else -1)
            for y in range(2 * step, ny, step):
                put(ex, y, '│', style)
            if nx > 0:
                put(ex, ny, '╰' if ny > 0 else '╭', style)
                hline(ex + 1, x0 - 1, ny, style)
            else:
                put(ex, ny, '╯' if ny > 0 else '╮', style)
                hline(x0 + nw, ex - 1, ny, style)

        # Trail: root ── entry ── entry, the current list marked.
        rects = self._trail_rects()
        if rects:
            _l, rx, _ry = self._map_nodes[self.trail_root]
            rx0, _y, rw, _h = self._node_rect(self.trail_root)
            edge = rx0 + rw if rx >= 0 else rx0
            for i, (bx, by, bw, text) in enumerate(rects):
                if rx >= 0:
                    hline(edge, bx - 1, by + 1, S_LINE_ON)
                    edge = bx + bw
                else:
                    hline(bx + bw, edge - 1, by + 1, S_LINE_ON)
                    edge = bx
                here = i == self.trail_pos
                style = (S_NODE_SEL if self.sel == ('trail', i)
                         else S_HERE if here else S_NODE)
                fill(bx, by, bw, 3, style)
                put(bx + 2, by + 1, ('● ' if here else '○ ') + text, style)

        # Nodes.
        for nid, (label, _x, _y) in self._map_nodes.items():
            x0, y0, nw, _nh = self._node_rect(nid)
            if nid == self.sel and self.open_id is None:
                style = S_NODE_SEL
            elif nid == self.open_id:
                style = S_HERE
            elif nid == HUB:
                style = S_HUB
            elif nid in self.dim_ids:
                style = S_NODE_DIM
            else:
                style = S_NODE
            fill(x0, y0, nw, 3, style)
            put(x0 + 2, y0 + 1, label, style)

        # The open node's rows, as a block under it.
        if self.open_id is not None:
            rows = self.node_rows.get(self.open_id) or []
            bx, by, bw, first, count = self._block_geometry(h)
            fill(bx, by, bw, count + 1, S_ROW)
            sel_n = sum(1 for r in rows[:self.row_idx + 1] if r.get('payload') is not None)
            total = sum(1 for r in rows if r.get('payload') is not None)
            more = ''
            if first > 0:
                more += '↑'
            if first + count < len(rows):
                more += '↓'
            info = f'{sel_n}/{total} {more}'.rstrip() if total else ''
            put(bx + bw - _width(info) - 2, by, info, S_MUTED)
            for i in range(count):
                r = rows[first + i]
                idx = first + i
                if r.get('header'):
                    style, lead = S_HEAD, ' '
                elif r.get('payload') is None:
                    style, lead = S_MUTED, ' '
                elif idx == self.row_idx:
                    style, lead = S_ROW_SEL, ' ▸ '
                else:
                    style, lead = S_ROW, '   '
                room = bw - (10 if i == 0 else 2)
                text = _clip(lead + (r.get('label') or ''), room)
                if style == S_ROW_SEL:
                    put(bx, by + i, ' ' * (bw if i else bw - 9), style)
                put(bx, by + i, text, style)

        styles = self._pal
        lines = []
        for y in range(h):
            crow, srow = ch[y], st[y]
            segs, run, cur = [], [], srow[0]
            for x in range(w):
                s = srow[x]
                if s != cur:
                    segs.append(Segment(''.join(run), styles[cur]))
                    run, cur = [], s
                run.append(crow[x])
            segs.append(Segment(''.join(run), styles[cur]))
            lines.append(Strip(segs, w))
        self._frame = lines

    def render_line(self, y):
        if self._frame is None or len(self._frame) != self.size.height:
            self._compose_frame()
        if 0 <= y < len(self._frame):
            return self._frame[y]
        return Strip.blank(self.size.width)
