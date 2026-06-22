"""
library.py — persistent user library + playback sessions.

Two JSON files live next to the script (both gitignored):
  library.json  — liked songs, saved playlists, pinned local folders, recent plays
  sessions.json — recent playback sessions (queue + position) used by "Resume"

Every track is the same dict shape used by youtube.py / offline.py:
  {id, title, uploader, duration, url, thumbnail}
Tracks are identified by 'id' (videoId online, file path offline), falling back
to 'url'.
"""

import json
import os
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB_FILE      = os.path.join(_HERE, 'library.json')
_SESSIONS_FILE = os.path.join(_HERE, 'sessions.json')

RECENT_CAP   = 100
SESSION_CAP  = 10

_LIB_DEFAULTS = {
    'liked':     [],   # [track]
    'playlists': [],   # [{'name': str, 'tracks': [track]}]
    'folders':   [],   # [path]
    'recent':    [],   # [track], most-recent first
}


def _track_key(track):
    return track.get('id') or track.get('url') or ''


def _load(path, default):
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                merged = dict(default)
                merged.update({k: data[k] for k in default if k in data})
                return merged
        except Exception:
            pass
    return dict(default)


def _save(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


class Library:
    def __init__(self):
        self._lib = _load(_LIB_FILE, _LIB_DEFAULTS)
        self._sessions = _load(_SESSIONS_FILE, {'sessions': []})

    # ── Liked ───────────────────────────────────────────────────────────────

    def liked(self):
        return list(self._lib['liked'])

    def is_liked(self, track_or_id):
        key = track_or_id if isinstance(track_or_id, str) else _track_key(track_or_id)
        return any(_track_key(t) == key for t in self._lib['liked'])

    def toggle_like(self, track):
        """Add/remove a track from liked. Returns True if now liked."""
        key = _track_key(track)
        existing = [t for t in self._lib['liked'] if _track_key(t) == key]
        if existing:
            self._lib['liked'] = [t for t in self._lib['liked'] if _track_key(t) != key]
            _save(_LIB_FILE, self._lib)
            return False
        self._lib['liked'].insert(0, track)
        _save(_LIB_FILE, self._lib)
        return True

    # ── Recent ──────────────────────────────────────────────────────────────

    def recent(self):
        return list(self._lib['recent'])

    def add_recent(self, track):
        key = _track_key(track)
        if not key:
            return
        self._lib['recent'] = [t for t in self._lib['recent'] if _track_key(t) != key]
        self._lib['recent'].insert(0, track)
        del self._lib['recent'][RECENT_CAP:]
        _save(_LIB_FILE, self._lib)

    # ── Playlists ─────────────────────────────────────────────────────────────

    def playlists(self):
        return list(self._lib['playlists'])

    def get_playlist(self, name):
        for p in self._lib['playlists']:
            if p.get('name') == name:
                return p
        return None

    def save_playlist(self, name, tracks):
        """Create or overwrite a named playlist."""
        name = (name or '').strip()
        if not name:
            return
        self._lib['playlists'] = [p for p in self._lib['playlists'] if p.get('name') != name]
        self._lib['playlists'].append({'name': name, 'tracks': list(tracks)})
        _save(_LIB_FILE, self._lib)

    def delete_playlist(self, name):
        self._lib['playlists'] = [p for p in self._lib['playlists'] if p.get('name') != name]
        _save(_LIB_FILE, self._lib)

    # ── Pinned folders ────────────────────────────────────────────────────────

    def folders(self):
        return list(self._lib['folders'])

    def pin_folder(self, path):
        path = (path or '').strip()
        if not path or path in self._lib['folders']:
            return
        self._lib['folders'].insert(0, path)
        _save(_LIB_FILE, self._lib)

    def unpin_folder(self, path):
        self._lib['folders'] = [p for p in self._lib['folders'] if p != path]
        _save(_LIB_FILE, self._lib)

    # ── Sessions (resume) ─────────────────────────────────────────────────────

    def sessions(self):
        return list(self._sessions['sessions'])

    def get_session(self, sid):
        for s in self._sessions['sessions']:
            if s.get('id') == sid:
                return s
        return None

    def save_session(self, snapshot):
        """Store a playback snapshot at the front; keep newest SESSION_CAP.

        snapshot should include: title, queue, queue_idx, position, app_mode,
        shuffle, repeat. id + ts are added here.
        """
        if not snapshot.get('queue'):
            return None
        snap = dict(snapshot)
        snap['ts'] = time.time()
        snap['id'] = str(int(snap['ts'] * 1000))
        self._sessions['sessions'].insert(0, snap)
        del self._sessions['sessions'][SESSION_CAP:]
        _save(_SESSIONS_FILE, self._sessions)
        return snap['id']

    def delete_session(self, sid):
        self._sessions['sessions'] = [
            s for s in self._sessions['sessions'] if s.get('id') != sid
        ]
        _save(_SESSIONS_FILE, self._sessions)


if __name__ == '__main__':
    import tempfile
    # Use throwaway files so the self-test never touches the real library.
    _LIB_FILE = os.path.join(tempfile.gettempdir(), 'yttui_lib_test.json')
    _SESSIONS_FILE = os.path.join(tempfile.gettempdir(), 'yttui_sess_test.json')
    for f in (_LIB_FILE, _SESSIONS_FILE):
        if os.path.isfile(f):
            os.remove(f)

    lib = Library()
    t1 = {'id': 'a', 'title': 'Song A', 'uploader': 'X', 'duration': 100, 'url': 'u1', 'thumbnail': ''}
    t2 = {'id': 'b', 'title': 'Song B', 'uploader': 'Y', 'duration': 200, 'url': 'u2', 'thumbnail': ''}

    assert lib.toggle_like(t1) is True
    assert lib.is_liked(t1) and not lib.is_liked(t2)
    assert lib.toggle_like(t1) is False and not lib.is_liked(t1)

    lib.add_recent(t1); lib.add_recent(t2); lib.add_recent(t1)
    assert [t['id'] for t in lib.recent()] == ['a', 'b'], lib.recent()

    lib.save_playlist('Fav', [t1, t2])
    lib.save_playlist('Fav', [t2])           # overwrite
    assert len(lib.playlists()) == 1 and len(lib.get_playlist('Fav')['tracks']) == 1

    lib.pin_folder('/music'); lib.pin_folder('/music')
    assert lib.folders() == ['/music']

    sid = lib.save_session({'title': 'Song A', 'queue': [t1, t2], 'queue_idx': 1,
                            'position': 42.0, 'app_mode': 'online',
                            'shuffle': False, 'repeat': 'all'})
    assert lib.get_session(sid)['position'] == 42.0

    # Reload from disk → persistence round-trip
    lib2 = Library()
    assert lib2.get_playlist('Fav') and lib2.folders() == ['/music']
    assert lib2.get_session(sid)['queue_idx'] == 1

    for f in (_LIB_FILE, _SESSIONS_FILE):
        os.remove(f)
    print('library.py self-test OK')
