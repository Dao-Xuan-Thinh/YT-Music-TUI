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
    'playlists': [],   # [{'name': str, 'tracks': [track], 'ts': float}]
    'folders':   [],   # [path]
    'recent':    [],   # [track], most-recent first
    # Cross-device sync bookkeeping (see export_sync/merge_sync): when each
    # like happened, and when things were deleted (tombstones — so an unlike/
    # delete on one device wins over a stale copy on another).
    'liked_ts':  {},   # {track_key: ts}
    'tombstones': {'liked': {}, 'playlists': {}, 'sessions': {}},
}

TOMBSTONE_TTL = 90 * 86400   # forget deletions after 90 days
SYNC_SESSION_CAP = 5         # newest sessions each device publishes
SYNC_QUEUE_CAP = 200         # tracks per published session queue


def _track_key(track):
    return track.get('id') or track.get('url') or ''


def _sanitize_tracks(tracks):
    """Repair persisted track dicts in place: a direct googlevideo stream URL
    (leaked by an old premium-retry bug) expires within hours — restore the
    canonical watch URL from the id, and drop stray one-shot play keys."""
    for t in tracks:
        if not isinstance(t, dict):
            continue
        t.pop('_direct_url', None)
        t.pop('_direct_ts', None)
        url = t.get('url') or ''
        if 'googlevideo' in url and t.get('id'):
            t['url'] = f'https://www.youtube.com/watch?v={t["id"]}'
    return tracks


def _load(path, default):
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                merged = json.loads(json.dumps(default))   # deep copy
                merged.update({k: data[k] for k in default if k in data})
                return merged
        except Exception:
            pass
    return json.loads(json.dumps(default))


def _lite(track):
    """Compact sync form of a track (url/thumbnail rebuilt from id on import)."""
    return {'id': track.get('id') or '', 'title': track.get('title') or '',
            'uploader': track.get('uploader') or '',
            'duration': int(track.get('duration') or 0)}


def _from_lite(t):
    return {'id': t.get('id') or '', 'title': t.get('title') or 'Unknown',
            'uploader': t.get('uploader') or '',
            'duration': int(t.get('duration') or 0),
            'url': f'https://www.youtube.com/watch?v={t.get("id")}',
            'thumbnail': ''}


def _syncable(track):
    """Only online tracks travel across devices (offline ids are file paths)."""
    tid = track.get('id') or ''
    url = track.get('url') or ''
    return bool(tid) and '/' not in tid and '\\' not in tid \
        and url.startswith('http')


def merge_sync(exports, now=None):
    """Merge every device's library export (list of dicts as produced by
    Library.export_sync) into one authoritative state. Pure — no I/O.

    Rules: per liked track / per playlist name / per session id, the newest
    timestamp wins; a deletion tombstone beats an older add and loses to a
    newer one (ties go to the add). Tombstones older than TOMBSTONE_TTL drop.
    Returns the same shape as an export (ready for Library.apply_sync)."""
    now = now or time.time()
    cutoff = now - TOMBSTONE_TTL

    # liked: key -> (ts, lite|None); None = tombstone winner. Adds use >= and
    # removals use > so an equal-timestamp tie always resolves to "liked".
    liked = {}
    for ex in exports:
        for e in ex.get('liked', []):
            t, ts = e.get('t') or {}, float(e.get('ts') or 0)
            key = t.get('id') or ''
            if key and (key not in liked or ts >= liked[key][0]):
                liked[key] = (ts, t)
        for key, ts in (ex.get('liked_rm') or {}).items():
            ts = float(ts or 0)
            if ts < cutoff:
                continue
            if key not in liked or ts > liked[key][0]:
                liked[key] = (ts, None)

    # playlists: name -> (ts, tracks|None)
    pls = {}
    for ex in exports:
        for p in ex.get('playlists', []):
            name, ts = p.get('name') or '', float(p.get('ts') or 0)
            if name and (name not in pls or ts >= pls[name][0]):
                pls[name] = (ts, p.get('tracks') or [])
        for name, ts in (ex.get('playlists_rm') or {}).items():
            ts = float(ts or 0)
            if ts < cutoff:
                continue
            if name not in pls or ts > pls[name][0]:
                pls[name] = (ts, None)

    # sessions: id -> session (ids are unique per save; rm beats presence)
    sess = {}
    sess_rm = {}
    for ex in exports:
        for s in ex.get('sessions', []):
            sid = s.get('id') or ''
            if sid and (sid not in sess
                        or float(s.get('ts') or 0) > float(sess[sid].get('ts') or 0)):
                sess[sid] = s
        for sid, ts in (ex.get('sessions_rm') or {}).items():
            ts = float(ts or 0)
            if ts >= cutoff:
                sess_rm[sid] = max(ts, sess_rm.get(sid, 0))
    for sid, ts in sess_rm.items():
        if sid in sess and ts >= float(sess[sid].get('ts') or 0):
            del sess[sid]

    return {
        'liked': [{'t': t, 'ts': ts}
                  for key, (ts, t) in sorted(liked.items(),
                                             key=lambda kv: -kv[1][0])
                  if t is not None],
        'liked_rm': {k: ts for k, (ts, t) in liked.items() if t is None},
        'playlists': [{'name': n, 'tracks': tr, 'ts': ts}
                      for n, (ts, tr) in sorted(pls.items())
                      if tr is not None],
        'playlists_rm': {n: ts for n, (ts, tr) in pls.items() if tr is None},
        'sessions': sorted(sess.values(),
                           key=lambda s: -float(s.get('ts') or 0))[:SESSION_CAP],
        'sessions_rm': sess_rm,
    }


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
        # Heal entries poisoned by the old premium-retry bug (expiring stream URLs).
        _sanitize_tracks(self._lib.get('liked', []))
        _sanitize_tracks(self._lib.get('recent', []))
        for pl in self._lib.get('playlists', []):
            _sanitize_tracks(pl.get('tracks', []))
        for s in self._sessions.get('sessions', []):
            _sanitize_tracks(s.get('queue', []))

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
            self._lib['liked_ts'].pop(key, None)
            self._lib['tombstones']['liked'][key] = time.time()
            _save(_LIB_FILE, self._lib)
            return False
        self._lib['liked'].insert(0, track)
        self._lib['liked_ts'][key] = time.time()
        self._lib['tombstones']['liked'].pop(key, None)
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

    def remove_recent(self, track_or_id):
        """Drop a single track from recent (by id/url). No-op if absent."""
        key = track_or_id if isinstance(track_or_id, str) else _track_key(track_or_id)
        if not key:
            return
        before = len(self._lib['recent'])
        self._lib['recent'] = [t for t in self._lib['recent'] if _track_key(t) != key]
        if len(self._lib['recent']) != before:
            _save(_LIB_FILE, self._lib)

    def clear_recent(self):
        """Empty the recent list."""
        if self._lib['recent']:
            self._lib['recent'] = []
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
        self._lib['playlists'].append({'name': name, 'tracks': list(tracks),
                                       'ts': time.time()})
        self._lib['tombstones']['playlists'].pop(name, None)
        _save(_LIB_FILE, self._lib)

    def delete_playlist(self, name):
        self._lib['playlists'] = [p for p in self._lib['playlists'] if p.get('name') != name]
        self._lib['tombstones']['playlists'][name] = time.time()
        _save(_LIB_FILE, self._lib)

    def rename_playlist(self, old, new):
        """Rename a saved playlist. Returns True on success.

        No-op (returns False) if names are blank, the source is missing, or the
        target name already exists (and isn't just the same playlist).
        """
        old = (old or '').strip()
        new = (new or '').strip()
        if not old or not new:
            return False
        src = self.get_playlist(old)
        if src is None:
            return False
        if new != old and self.get_playlist(new) is not None:
            return False   # refuse to clobber a different existing playlist
        self.save_playlist(new, src['tracks'])
        if new != old:
            self.delete_playlist(old)
        return True

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
        self._lib['tombstones']['sessions'][sid] = time.time()
        _save(_LIB_FILE, self._lib)
        _save(_SESSIONS_FILE, self._sessions)

    # ── Cross-device sync (see merge_sync for the rules) ─────────────────────

    def export_sync(self, device_name=''):
        """This device's library as a compact sync blob (goes into our gist
        file). Offline/local entries stay local — they can't play elsewhere."""
        ts_map = self._lib.get('liked_ts', {})
        liked = [{'t': _lite(t), 'ts': float(ts_map.get(_track_key(t), 0))}
                 for t in self._lib['liked'] if _syncable(t)]
        playlists = [{'name': p['name'],
                      'tracks': [_lite(t) for t in p.get('tracks', [])
                                 if _syncable(t)][:SYNC_QUEUE_CAP],
                      'ts': float(p.get('ts', 0))}
                     for p in self._lib['playlists']]
        sessions = []
        for s in self._sessions['sessions'][:SYNC_SESSION_CAP]:
            if s.get('app_mode') == 'offline':
                continue
            queue = [_lite(t) for t in s.get('queue', [])
                     if _syncable(t)][:SYNC_QUEUE_CAP]
            if not queue:
                continue
            idx = min(int(s.get('queue_idx', 0)), len(queue) - 1)
            sessions.append({'id': s.get('id'), 'title': s.get('title', ''),
                             'queue': queue, 'queue_idx': idx,
                             'position': float(s.get('position', 0)),
                             'shuffle': bool(s.get('shuffle')),
                             'repeat': s.get('repeat', 'off'),
                             'ts': float(s.get('ts', 0)),
                             'device': s.get('device') or device_name})
        tomb = self._lib.get('tombstones', {})
        return {'liked': liked, 'liked_rm': dict(tomb.get('liked', {})),
                'playlists': playlists,
                'playlists_rm': dict(tomb.get('playlists', {})),
                'sessions': sessions,
                'sessions_rm': dict(tomb.get('sessions', {}))}

    def _sync_fingerprint(self):
        return json.dumps([
            sorted((_track_key(t), self._lib['liked_ts'].get(_track_key(t), 0))
                   for t in self._lib['liked']),
            sorted((p['name'], p.get('ts', 0)) for p in self._lib['playlists']),
            sorted(s.get('id') or '' for s in self._sessions['sessions']),
        ], sort_keys=True)

    def apply_sync(self, merged, own_device_name=''):
        """Apply a merge_sync result to local state. Returns True if anything
        changed. Local dicts are kept when present (they carry url/thumbnail);
        merged-only entries are rebuilt from their lite form."""
        before = self._sync_fingerprint()

        local_liked = {_track_key(t): t for t in self._lib['liked']}
        self._lib['liked'] = [local_liked.get(e['t'].get('id'),
                                              _from_lite(e['t']))
                              for e in merged.get('liked', [])]
        # Keep local-only (offline) likes — they were excluded from the export.
        merged_keys = {e['t'].get('id') for e in merged.get('liked', [])}
        for key, t in local_liked.items():
            if not _syncable(t) and key not in merged_keys:
                self._lib['liked'].append(t)
        self._lib['liked_ts'] = {e['t'].get('id'): e['ts']
                                 for e in merged.get('liked', [])}

        local_pls = {p['name']: p for p in self._lib['playlists']}
        new_pls = []
        for p in merged.get('playlists', []):
            loc = local_pls.get(p['name'])
            if loc is not None and float(loc.get('ts', 0)) >= p['ts']:
                new_pls.append(loc)       # local copy is the winner — richer dicts
            else:
                new_pls.append({'name': p['name'],
                                'tracks': [_from_lite(t) for t in p['tracks']],
                                'ts': p['ts']})
        # Never drop a local playlist just because the merge didn't mention it
        # (offline-only playlists don't export) — only a tombstone deletes.
        merged_names = {p['name'] for p in merged.get('playlists', [])}
        for name, p in local_pls.items():
            if name not in merged_names \
                    and name not in merged.get('playlists_rm', {}):
                new_pls.append(p)
        self._lib['playlists'] = new_pls

        local_sess = {s.get('id'): s for s in self._sessions['sessions']}
        new_sess = []
        for s in merged.get('sessions', []):
            loc = local_sess.get(s.get('id'))
            if loc is not None:
                new_sess.append(loc)
            else:
                s = dict(s)
                s['queue'] = [_from_lite(t) for t in s.get('queue', [])]
                s['app_mode'] = 'online'
                new_sess.append(s)
        # Keep local-only sessions the merge didn't cover (offline ones).
        merged_ids = {s.get('id') for s in merged.get('sessions', [])}
        for sid, s in local_sess.items():
            if sid not in merged_ids \
                    and sid not in merged.get('sessions_rm', {}):
                new_sess.append(s)
        new_sess.sort(key=lambda s: -float(s.get('ts') or 0))
        self._sessions['sessions'] = new_sess[:SESSION_CAP]

        self._lib['tombstones'] = {
            'liked': merged.get('liked_rm', {}),
            'playlists': merged.get('playlists_rm', {}),
            'sessions': merged.get('sessions_rm', {}),
        }
        changed = self._sync_fingerprint() != before
        if changed:
            _save(_LIB_FILE, self._lib)
            _save(_SESSIONS_FILE, self._sessions)
        return changed


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
    lib.remove_recent(t1)                     # drop one by track
    assert [t['id'] for t in lib.recent()] == ['b'], lib.recent()
    lib.clear_recent()
    assert lib.recent() == []

    lib.save_playlist('Fav', [t1, t2])
    lib.save_playlist('Fav', [t2])           # overwrite
    assert len(lib.playlists()) == 1 and len(lib.get_playlist('Fav')['tracks']) == 1
    assert lib.rename_playlist('Fav', 'Best') is True
    assert lib.get_playlist('Fav') is None and lib.get_playlist('Best') is not None
    assert lib.rename_playlist('Best', '') is False        # blank target → no-op
    assert lib.rename_playlist('Nope', 'X') is False       # missing source → no-op

    lib.pin_folder('/music'); lib.pin_folder('/music')
    assert lib.folders() == ['/music']

    sid = lib.save_session({'title': 'Song A', 'queue': [t1, t2], 'queue_idx': 1,
                            'position': 42.0, 'app_mode': 'online',
                            'shuffle': False, 'repeat': 'all'})
    assert lib.get_session(sid)['position'] == 42.0

    # Reload from disk → persistence round-trip
    lib2 = Library()
    assert lib2.get_playlist('Best') and lib2.folders() == ['/music']
    assert lib2.get_session(sid)['queue_idx'] == 1

    for f in (_LIB_FILE, _SESSIONS_FILE):
        os.remove(f)
    print('library.py self-test OK')
