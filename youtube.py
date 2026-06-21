"""
youtube.py — yt-dlp wrapper for search, URL resolution, and metadata.
"""

import urllib.parse
import yt_dlp


class _SilentLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


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

    Note: yt-dlp's YouTube Music search extractor (_music_reponsive_list_entry)
    only returns 4 fields (id, title, url, ie_key) — no artist/uploader/duration.
    All modes use ytsearch{n}: which provides full metadata via _extract_video().
    """
    opts = _ydl_opts(cookies_file, {'extract_flat': True})

    def _search_yt(n):
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

    if source in ('yt', 'ytm'):
        return _search_yt(max_results)

    # 'both': fetch double results and deduplicate by video ID
    results = _search_yt(max_results * 2)
    seen = set()
    deduped = []
    for r in results:
        if r['id'] and r['id'] not in seen:
            seen.add(r['id'])
            deduped.append(r)
        elif not r['id']:
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
