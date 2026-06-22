"""
youtube.py — YouTube / YouTube Music wrapper.

YouTube Music (search + playlists) goes through ytmusicapi, which paginates
large playlists fully via YTM's own continuation API and returns artist/album
metadata natively. (yt-dlp's flat playlist extraction caps YTM playlists at
~108 entries — an upstream bug — and provides no artist for flat entries.)
Regular YouTube search/URLs and all audio streaming stay on yt-dlp/mpv.
"""

import urllib.parse
import yt_dlp


class _SilentLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


# ── ytmusicapi (YouTube Music) ────────────────────────────────────────────────

_ytm = None

def _get_ytm():
    """Lazily create an unauthenticated YTMusic client (works for public data)."""
    global _ytm
    if _ytm is None:
        from ytmusicapi import YTMusic
        _ytm = YTMusic()
    return _ytm


def _parse_ytm_duration(t):
    """ytmusicapi gives duration_seconds, or 'duration' as 'M:SS'/'H:MM:SS'."""
    ds = t.get('duration_seconds')
    if ds:
        return int(ds)
    text = t.get('duration') or ''
    parts = text.split(':')
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + int(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + int(s)
    except ValueError:
        pass
    return 0


def _ytm_track_to_dict(t):
    """Map a ytmusicapi track to our standard track dict (same shape as yt-dlp)."""
    vid = t.get('videoId') or ''
    artists = ', '.join(
        a['name'] for a in (t.get('artists') or []) if a.get('name')
    )
    thumbs = t.get('thumbnails') or []
    return {
        'id': vid,
        'title': t.get('title') or 'Unknown',
        'uploader': artists,
        'duration': _parse_ytm_duration(t),
        # Canonical www URL (same videoId): mpv's ytdl_hook handles it on every
        # OS, whereas music.youtube.com/watch URLs fail to load via mpv on Linux.
        'url': f'https://www.youtube.com/watch?v={vid}',
        'thumbnail': thumbs[-1]['url'] if thumbs else '',
    }


def ytm_playlist_id(inp):
    """
    Return the playlist id if inp is a YouTube/YT-Music *playlist* URL, else None.
    Accepts any youtube.com host (www / music / m / plain) so a copied
    www.youtube.com/playlist URL still routes through ytmusicapi (full list),
    not the yt-dlp path that caps at ~108. Watch URLs (?v=…&list=…) are excluded.
    """
    if not _is_url(inp):
        return None
    parsed = urllib.parse.urlparse(inp)
    if 'youtube.com' not in parsed.netloc:
        return None
    params = urllib.parse.parse_qs(parsed.query)
    if 'list' in params and 'watch' not in parsed.path:
        return params['list'][0]
    return None


def ytm_playlist(playlist_id, limit=None):
    """
    Fetch a YouTube Music playlist's tracks via ytmusicapi.
    limit=None fetches all tracks (paginated). Returns list of track dicts.
    """
    data = _get_ytm().get_playlist(playlist_id, limit=limit)
    return [
        _ytm_track_to_dict(t)
        for t in data.get('tracks', [])
        if t.get('videoId')
    ]


def ytm_search(query, max_results=15):
    """Search YouTube Music for songs via ytmusicapi. Returns list of track dicts."""
    results = _get_ytm().search(query, filter='songs', limit=max_results)
    out = [_ytm_track_to_dict(t) for t in results if t.get('videoId')]
    return out[:max_results]


def _ydl_opts(cookies_file=None, extra=None):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'logger': _SilentLogger(),
    }
    if cookies_file:
        opts['cookiefile'] = cookies_file
    if extra:
        opts.update(extra)
    return opts


def _is_url(text):
    return text.startswith('http://') or text.startswith('https://')


def _entry_to_dict(e):
    vid_id = e.get('id') or ''
    url = (
        e.get('webpage_url')
        or e.get('url')
        or (f'https://www.youtube.com/watch?v={vid_id}' if vid_id else '')
    )
    duration = e.get('duration') or 0
    return {
        'id': vid_id,
        'title': e.get('title') or 'Unknown',
        'uploader': e.get('artist') or e.get('uploader') or e.get('channel') or '',
        'duration': int(duration),
        'url': url,
        'thumbnail': e.get('thumbnail') or '',
    }


def search(query, source='ytm', max_results=15, cookies_file=None):
    """
    Keyword search. source: 'ytm', 'yt', or 'both'.
    Returns list of track dicts.

    'ytm' uses ytmusicapi (real YouTube Music ranking + native artist metadata).
    'yt'  uses yt-dlp ytsearch{n}: (full metadata via _extract_video()).
    """
    def _search_yt(n):
        opts = _ydl_opts(cookies_file, {'extract_flat': True})
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f'ytsearch{n}:{query}', download=False)
            entries = info.get('entries') or []
            for e in entries:
                if not e.get('webpage_url') and e.get('id'):
                    e['webpage_url'] = f'https://www.youtube.com/watch?v={e["id"]}'
            return [_entry_to_dict(e) for e in entries]
        except Exception:
            return []

    def _search_ytm(n):
        try:
            return ytm_search(query, max_results=n)
        except Exception:
            return []

    if source == 'ytm':
        results = _search_ytm(max_results)
        return results if results else _search_yt(max_results)

    if source == 'yt':
        return _search_yt(max_results)

    # 'both': merge YTM + YouTube, dedupe by video ID
    merged = _search_ytm(max_results) + _search_yt(max_results)
    seen = set()
    deduped = []
    for r in merged:
        if r['id'] and r['id'] in seen:
            continue
        if r['id']:
            seen.add(r['id'])
        deduped.append(r)
    return deduped[:max_results]


def resolve(inp, source='ytm', cookies_file=None):
    """
    Smart entry point: URL (video/playlist) or keyword search.
    Always returns a list of track dicts.
    """
    if not _is_url(inp):
        return search(inp, source=source, cookies_file=cookies_file)

    # It's a URL — determine if playlist or single video
    parsed = urllib.parse.urlparse(inp)
    params = urllib.parse.parse_qs(parsed.query)
    is_playlist = 'list' in params and 'watch' not in parsed.path

    # Any YouTube playlist URL → ytmusicapi (full pagination + native artists).
    # Falls back to the yt-dlp path on any failure (e.g. non-music playlists).
    if is_playlist and 'youtube.com' in parsed.netloc:
        playlist_id = params['list'][0]
        try:
            results = ytm_playlist(playlist_id, limit=None)
            if results:
                return results
        except Exception:
            pass

    opts = _ydl_opts(cookies_file, {'extract_flat': 'in_playlist', 'lazy_playlist': False})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(inp, download=False)
    except Exception as exc:
        raise RuntimeError(f'Failed to resolve URL: {exc}') from exc

    # Playlist / channel
    if info.get('_type') == 'playlist' or is_playlist:
        entries = info.get('entries') or []
        results = []
        for e in entries:
            if e:
                results.append(_entry_to_dict(e))
        return results

    # Single video
    return [_entry_to_dict(info)]


def get_info(url, cookies_file=None):
    """Full metadata for a single video URL (used for now-playing bar)."""
    opts = _ydl_opts(cookies_file)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return _entry_to_dict(info)
    except Exception as exc:
        raise RuntimeError(f'Failed to get info: {exc}') from exc


def format_duration(seconds):
    """Format integer seconds as M:SS or H:MM:SS."""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m}:{s:02d}'


if __name__ == '__main__':
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    query = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else 'lofi hip hop'
    print(f'Resolving: {query!r}\n')
    try:
        results = resolve(query)
    except Exception as e:
        print(f'Error: {e}')
        sys.exit(1)

    if not results:
        print('No results.')
        sys.exit(0)

    print(f'{"#":<3} {"Title":<45} {"Artist":<25} {"Duration":>8}')
    print('-' * 85)
    for i, r in enumerate(results, 1):
        title = r['title'][:43] + '..' if len(r['title']) > 45 else r['title']
        artist = r['uploader'][:23] + '..' if len(r['uploader']) > 25 else r['uploader']
        dur = format_duration(r['duration'])
        print(f'{i:<3} {title:<45} {artist:<25} {dur:>8}')
    print(f'\n{len(results)} result(s).')
