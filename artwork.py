"""
artwork.py — album/song covers for the TUI side panel and the OS now-playing
panel.

Two jobs, one disk cache:
- `fetch(track)` downloads the cover once per track id into `.art-cache/` and
  returns the local path (blocking — callers run it on a daemon thread).
- `render(path, cols, rows)` turns that file into terminal cells.

Rendering uses HALF BLOCKS: one `▀` per cell carries two pixels — the top one
as the foreground color, the bottom one as the background — so a cell is square
even though a terminal cell is roughly twice as tall as it is wide. That
doubles the vertical resolution for free and is why the result reads as an
image rather than as text. `ascii_art()` is the no-color fallback.

Pillow is an OPTIONAL dependency (requirements.txt, below the `# optional`
marker). Without it `available()` is False and every caller simply shows
nothing extra — same rule as the media-key backends.
"""

import hashlib
import os
import re
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(_HERE, '.art-cache')

_TIMEOUT = 10
_MAX_BYTES = 4 * 1024 * 1024     # a cover is ~50 KB; this is just a sanity cap

# Google's image hosts take the wanted size in the URL. ytmusicapi hands out
# 60x60 or 120x120 thumbnails, which look like mud once blown up to a panel —
# ask the same URL for a big square instead.
_GOOG_SIZE = re.compile(r'=w\d+-h\d+')
_WANT = '=w544-h544'

# One rendered cover is reused across poll ticks; only the geometry or the
# track changes it. Keyed on (path, cols, rows).
_render_cache = {}
_render_lock = threading.Lock()


def available() -> bool:
    """True when covers can actually be decoded (Pillow installed)."""
    try:
        import PIL  # noqa: F401
        return True
    except Exception:
        return False


def url_for(track) -> str:
    """Best cover URL for a track dict, or '' when there can't be one.

    Prefers the thumbnail the search/feed handed us; falls back to YouTube's
    per-video image, which keeps covers working for library/recent entries
    (library.py stores tracks in a compact form that drops the thumbnail)."""
    if not isinstance(track, dict):
        return ''
    url = (track.get('thumbnail') or '').strip()
    if url:
        return _GOOG_SIZE.sub(_WANT, url)
    vid = (track.get('id') or '').strip()
    if vid and (track.get('url') or '').startswith('http'):
        return f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg'
    return ''


def _cache_path(url: str) -> str:
    return os.path.join(_CACHE_DIR, hashlib.sha1(url.encode()).hexdigest())


def cached(track) -> str:
    """Local path if this track's cover is already on disk, else ''."""
    url = url_for(track)
    if not url:
        return ''
    path = _cache_path(url)
    return path if os.path.isfile(path) else ''


def fetch(track) -> str:
    """Download the cover (once) and return its local path, or '' on failure.
    Blocking: call from a daemon thread."""
    url = url_for(track)
    if not url:
        return ''
    path = _cache_path(url)
    if os.path.isfile(path):
        return path
    try:
        import requests
        os.makedirs(_CACHE_DIR, exist_ok=True)
        r = requests.get(url, timeout=_TIMEOUT, stream=True)
        r.raise_for_status()
        body = b''
        for chunk in r.iter_content(64 * 1024):
            body += chunk
            if len(body) > _MAX_BYTES:
                return ''
        tmp = path + '.part'
        with open(tmp, 'wb') as f:
            f.write(body)
        os.replace(tmp, path)       # never leave a half-written file in cache
        return path
    except Exception:
        return ''


def fit(img_w: int, img_h: int, max_cols: int, max_rows: int):
    """Cell size that keeps the image's aspect ratio inside the box.

    A cell is 1 unit wide and 2 units tall, and half blocks give 2 pixels per
    cell vertically — so `cols x rows` cells show a `cols x 2*rows` pixel grid
    at its true aspect ratio."""
    if img_w <= 0 or img_h <= 0 or max_cols <= 0 or max_rows <= 0:
        return 0, 0
    cols = max_cols
    rows = max(1, round(cols * img_h / img_w / 2))
    if rows > max_rows:
        rows = max_rows
        cols = max(1, min(max_cols, round(rows * 2 * img_w / img_h)))
    return cols, rows


def render(path: str, max_cols: int, max_rows: int, ascii_only: bool = False):
    """A Rich `Text` of the cover, at most `max_cols` x `max_rows` cells.
    Returns None when the image can't be read (missing Pillow, bad file)."""
    if not path or max_cols < 2 or max_rows < 2:
        return None
    key = (path, max_cols, max_rows, ascii_only)
    with _render_lock:
        hit = _render_cache.get(key)
    if hit is not None:
        return hit
    try:
        from PIL import Image
        from rich.style import Style
        from rich.text import Text
    except Exception:
        return None
    try:
        with Image.open(path) as im:
            im = _autocrop(im.convert('RGB'))
            cols, rows = fit(im.width, im.height, max_cols, max_rows)
            if cols < 2 or rows < 1:
                return None
            if ascii_only:
                out = _ascii_text(Image, im, cols, rows)
            else:
                small = im.resize((cols, rows * 2), Image.LANCZOS)
                px = small.load()
                out = Text(no_wrap=True, overflow='crop')
                for y in range(rows):
                    for x in range(cols):
                        tr, tg, tb = px[x, y * 2]
                        br, bg, bb = px[x, y * 2 + 1]
                        out.append('▀', Style(
                            color=f'#{tr:02x}{tg:02x}{tb:02x}',
                            bgcolor=f'#{br:02x}{bg:02x}{bb:02x}'))
                    if y != rows - 1:
                        out.append('\n')
    except Exception:
        return None
    with _render_lock:
        if len(_render_cache) > 8:      # tiny: one cover, a few sizes
            _render_cache.clear()
        _render_cache[key] = out
    return out


def _autocrop(im):
    """Trim a uniform border. YouTube's per-video image is always 4:3, so a
    16:9 frame arrives letterboxed and a square cover arrives pillarboxed —
    drawn as-is, the panel would be half black bars. Each side is measured on
    its own, because a cover usually has bars on one axis only, and a crop that
    would eat most of the picture is ignored (a dark cover isn't a border)."""
    try:
        from PIL import Image, ImageChops
        for corner in ((0, 0), (im.width - 1, im.height - 1)):
            bg = Image.new('RGB', im.size, im.getpixel(corner))
            mask = ImageChops.difference(im, bg).convert('L').point(
                lambda v: 255 if v > 10 else 0)
            box = mask.getbbox()
            if not box:
                continue
            w, h = box[2] - box[0], box[3] - box[1]
            if w * h < im.width * im.height * 0.15:
                continue    # that's not a border, that's the whole picture
            if w < im.width or h < im.height:
                im = im.crop(box)
        return im
    except Exception:
        return im


# Dark → light: the glyph ramp for the ASCII renderer. Each character still
# carries its pixel's color, so a cover reads as text art without going gray.
_RAMP = ' .:-=+*#%@'


def _ascii_text(Image, im, cols: int, rows: int):
    from rich.style import Style
    from rich.text import Text
    from PIL import ImageOps
    small = im.resize((cols, rows), Image.LANCZOS)
    px = small.load()
    # Spread the luminance across the whole ramp before picking glyphs. Most
    # covers sit in the bottom third of the scale, and mapped straight they
    # come out as nothing but '.' and ':' — noise, not a picture. The cutoff
    # is deliberately steep: clipping the darkest and brightest 12% is what
    # makes the shapes read at 40-odd characters across. (Equalizing the
    # histogram instead looks better on a flat cover and blows out a
    # letterboxed one into a solid block of '@'.)
    gray = ImageOps.autocontrast(small.convert('L'), cutoff=12).load()
    out = Text(no_wrap=True, overflow='crop')
    last = len(_RAMP) - 1
    for y in range(rows):
        for x in range(cols):
            r, g, b = px[x, y]
            # Lift the color: a glyph covers maybe a third of its cell, so the
            # cover reads far darker than the image unless each pixel is pushed
            # toward full brightness.
            top = max(r, g, b) or 1
            r, g, b = (min(255, c * 255 // top) for c in (r, g, b))
            out.append(_RAMP[gray[x, y] * last // 255],
                       Style(color=f'#{r:02x}{g:02x}{b:02x}'))
        if y != rows - 1:
            out.append('\n')
    return out


def clear_cache() -> None:
    """Drop the rendered-cover memo (the files on disk stay)."""
    with _render_lock:
        _render_cache.clear()


if __name__ == '__main__':   # python artwork.py <url-or-file> [cols] [rows]
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else ''
    cols = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    rows = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    src = arg if os.path.isfile(arg) else fetch({'thumbnail': arg})
    if not src:
        print('could not get an image from:', arg)
        raise SystemExit(1)
    from rich.console import Console
    Console().print(render(src, cols, rows))
