"""
offline.py — Local audio folder scanner.

scan_folder() returns a list of track dicts with the same structure as youtube.py
so the existing DataTable population and playback queue work unchanged.
mpv plays local file paths via loadfile natively; no yt-dlp involved.
"""

import os
import pathlib

AUDIO_EXTS = {'.mp3', '.flac', '.m4a', '.ogg', '.aac', '.wav', '.opus', '.wma'}


def scan_folder(folder_path: str) -> list:
    """
    Recursively scan folder_path for audio files.
    Returns list of track dicts: {id, title, uploader, duration, url, thumbnail}.
    """
    results = []
    folder_path = os.path.abspath(folder_path)
    for root, dirs, files in os.walk(folder_path):
        dirs.sort()
        for fname in sorted(files):
            if pathlib.Path(fname).suffix.lower() not in AUDIO_EXTS:
                continue
            full_path = os.path.join(root, fname)
            title, artist, duration = _read_tags(full_path)
            results.append({
                'id': full_path,
                'title': title or pathlib.Path(fname).stem,
                'uploader': artist or '',
                'duration': duration,
                'url': full_path,
                'thumbnail': '',
            })
    return results


def _read_tags(path: str):
    """Return (title, artist, duration_seconds) from audio file tags via mutagen."""
    try:
        from mutagen import File
        f = File(path, easy=True)
        if f is None:
            return None, None, 0
        duration = int(getattr(f.info, 'length', 0))
        title  = (f.get('title')  or [None])[0]
        artist = (f.get('artist') or [None])[0]
        return (str(title) if title else None,
                str(artist) if artist else None,
                duration)
    except Exception:
        return None, None, 0


if __name__ == '__main__':
    import sys
    folder = sys.argv[1] if len(sys.argv) > 1 else '.'
    tracks = scan_folder(folder)
    print(f'Found {len(tracks)} audio file(s) in {folder!r}\n')
    print(f'{"#":<4} {"Title":<40} {"Artist":<25} {"Dur":>6}')
    print('-' * 80)
    for i, t in enumerate(tracks, 1):
        title  = t['title'][:38] + '..' if len(t['title']) > 40 else t['title']
        artist = t['uploader'][:23] + '..' if len(t['uploader']) > 25 else t['uploader']
        dur    = t['duration']
        m, s   = divmod(dur, 60)
        print(f'{i:<4} {title:<40} {artist:<25} {m}:{s:02d}')
