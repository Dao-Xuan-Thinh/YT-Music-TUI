"""
stats.py — listen-time tracking + cross-device sync via a private GitHub Gist.

Local state lives in stats.json next to the script (gitignored):
  {
    "days":   {"YYYY-MM-DD": seconds},          # this install's own counters
    "remote": {"<device-id>": {"device": name, "days": {...}}},  # last pull, all devices
    "last_sync": <unix time>
  }

Sync model: one gist (description marker below), one file per device
(ytm-stats-<device-id>.json). Each device only ever writes ITS OWN file, so
merging is just "sum every file per day" — no conflicts by construction.
The token is a GitHub PAT: classic with the `gist` scope, or fine-grained
with "Gists: read and write".
"""

import json
import os
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATS_FILE = os.path.join(_HERE, 'stats.json')

GIST_MARKER = 'ytm-tui listen stats'
_API = 'https://api.github.com'
_TIMEOUT = 10

_DEFAULTS = {
    'days': {},
    'remote': {},
    'last_sync': 0.0,
}


def _today():
    return time.strftime('%Y-%m-%d')


def _day_keys(n):
    """The last n local dates, oldest first, ending today."""
    now = time.time()
    return [time.strftime('%Y-%m-%d', time.localtime(now - 86400 * i))
            for i in range(n - 1, -1, -1)]


class StatsStore:
    """Thread-safe local counters + blocking gist sync (caller threads it)."""

    def __init__(self, path=_STATS_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._dirty = False
        self._last_error = ''      # sticky sync status ('' = ok / never tried)
        # Deep copy — a shallow dict(_DEFAULTS) would share the nested day/remote
        # dicts across every instance.
        self._data = json.loads(json.dumps(_DEFAULTS))
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                if isinstance(saved, dict):
                    for k in _DEFAULTS:
                        if k in saved:
                            self._data[k] = saved[k]
            except Exception:
                pass

    # ── Local accumulation ─────────────────────────────────────────────────

    def add(self, seconds):
        """Accumulate listened seconds into today's counter (memory only)."""
        if seconds <= 0:
            return
        with self._lock:
            day = _today()
            days = self._data['days']
            days[day] = float(days.get(day, 0)) + seconds
            self._dirty = True

    def flush(self):
        """Write stats.json if anything changed since the last write."""
        with self._lock:
            if not self._dirty:
                return
            data = json.loads(json.dumps(self._data))  # snapshot
            self._dirty = False
        try:
            with open(self._path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    # ── Merged views (local + remote devices) ──────────────────────────────

    def _merged_day_map(self, own_device_id=''):
        """day -> total seconds across all devices. For our own device the
        per-day value is max(local, remote copy) — the remote copy can be
        AHEAD of a wiped/older local store, never double-counted."""
        with self._lock:
            local = dict(self._data['days'])
            remote = {k: dict(v.get('days', {}))
                      for k, v in self._data['remote'].items()
                      if isinstance(v, dict)}
        own = remote.pop(own_device_id, {}) if own_device_id else {}
        merged = {}
        for day in set(local) | set(own):
            merged[day] = max(float(local.get(day, 0)), float(own.get(day, 0)))
        for days in remote.values():
            for day, secs in days.items():
                try:
                    merged[day] = merged.get(day, 0.0) + float(secs)
                except (TypeError, ValueError):
                    pass
        return merged

    def merged_days(self, n=7, own_device_id=''):
        """[(date_str, seconds)] for the last n days, oldest first."""
        merged = self._merged_day_map(own_device_id)
        return [(d, merged.get(d, 0.0)) for d in _day_keys(n)]

    def totals(self, own_device_id=''):
        merged = self._merged_day_map(own_device_id)
        week = set(_day_keys(7))
        return {
            'today': merged.get(_today(), 0.0),
            'week': sum(v for d, v in merged.items() if d in week),
            'all': sum(merged.values()),
        }

    def per_device(self, own_device_id='', own_device_name='this device'):
        """[(name, total_seconds)], this device first."""
        with self._lock:
            local = dict(self._data['days'])
            remote = {k: (v.get('device') or k[:8], dict(v.get('days', {})))
                      for k, v in self._data['remote'].items()
                      if isinstance(v, dict)}
        own_remote = remote.pop(own_device_id, ('', {}))[1] if own_device_id else {}
        own_total = sum(max(float(local.get(d, 0)), float(own_remote.get(d, 0)))
                        for d in set(local) | set(own_remote))
        out = [(own_device_name, own_total)]
        for name, days in remote.values():
            try:
                out.append((name, sum(float(s) for s in days.values())))
            except (TypeError, ValueError):
                pass
        return out

    def last_sync(self):
        with self._lock:
            return float(self._data.get('last_sync') or 0)

    def status_line(self, configured):
        if not configured:
            return 'sync: not configured — add a GitHub token in Settings (s)'
        if self._last_error:
            return f'sync: {self._last_error}'
        ts = self.last_sync()
        if not ts:
            return 'sync: waiting for first sync…'
        mins = int((time.time() - ts) // 60)
        return 'sync: just now' if mins < 1 else f'sync: {mins} min ago'

    # ── Gist sync (blocking; run on a daemon thread) ───────────────────────

    def sync(self, token, device_id, device_name, gist_id='', library_export=None):
        """Full cycle: resolve gist → pull all device files → merge-max our own
        → push our file → persist snapshot. Returns (ok, status_msg, gist_id
        or None if unchanged, merged_library or None). Never raises.

        `library_export` (Library.export_sync output) rides in our device file
        and, when given, the pull side merges every device's library blob via
        library.merge_sync — the caller applies the result on the UI thread."""
        import requests
        if not (token and device_id):
            return False, 'not configured', None, None
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        }
        orig_id = gist_id
        try:
            if not gist_id:
                gist_id = self._find_gist(headers)
            if gist_id:
                r = requests.get(f'{_API}/gists/{gist_id}', headers=headers,
                                 timeout=_TIMEOUT)
                if r.status_code == 404:
                    # Cached id points at a deleted gist — rediscover once.
                    gist_id = self._find_gist(headers)
                    r = (requests.get(f'{_API}/gists/{gist_id}', headers=headers,
                                      timeout=_TIMEOUT) if gist_id else None)
                if r is not None:
                    self._check(r)
            if not gist_id:
                gist_id = self._create_gist(headers, device_id, device_name)
                r = None
            remote = {}
            remote_libs = []      # other devices' library blobs (ours excluded)
            if r is not None:
                for fname, finfo in (r.json().get('files') or {}).items():
                    if not (fname.startswith('ytm-stats-') and fname.endswith('.json')):
                        continue
                    dev = fname[len('ytm-stats-'):-len('.json')]
                    try:
                        parsed = json.loads(finfo.get('content') or '{}')
                        remote[dev] = {'device': parsed.get('device') or dev[:8],
                                       'days': dict(parsed.get('days') or {})}
                        if dev != device_id and isinstance(parsed.get('library'), dict):
                            remote_libs.append(parsed['library'])
                    except Exception:
                        continue  # one bad file must not kill the merge
            # Cross-device library merge: our fresh export + everyone else's.
            merged_library = None
            if library_export is not None:
                import library as _library
                merged_library = _library.merge_sync([library_export] + remote_libs)
            # Merge-max our own remote copy into local (protects a wiped store).
            with self._lock:
                own = remote.get(device_id, {}).get('days', {})
                for day, secs in own.items():
                    try:
                        if float(secs) > float(self._data['days'].get(day, 0)):
                            self._data['days'][day] = float(secs)
                    except (TypeError, ValueError):
                        pass
                body = {'device': device_name, 'days': self._data['days']}
                if merged_library is not None:
                    # Publish the MERGED state, so this file already reflects
                    # everyone's edits the next time another device pulls.
                    body['library'] = merged_library
                payload = json.dumps(body, indent=1)
            # Push only our file.
            pr = requests.patch(
                f'{_API}/gists/{gist_id}', headers=headers, timeout=_TIMEOUT,
                json={'files': {f'ytm-stats-{device_id}.json': {'content': payload}}})
            self._check(pr)
            with self._lock:
                remote[device_id] = {'device': device_name,
                                     'days': dict(self._data['days'])}
                self._data['remote'] = remote
                self._data['last_sync'] = time.time()
                self._dirty = True
            self.flush()
            self._last_error = ''
            # Report the gist id back whenever it changed (created, or the cached
            # one was deleted and a fresh one was rediscovered) so the caller
            # persists it and stops re-resolving every cycle.
            return (True, 'synced', (gist_id if gist_id != orig_id else None),
                    merged_library)
        except _AuthError:
            self._last_error = 'token rejected'
            return False, 'token rejected', None, None
        except _RateLimited:
            self._last_error = 'rate limited'
            return False, 'rate limited', None, None
        except Exception:
            # Network / GitHub hiccup: keep last-success status, retry later.
            if not self._last_error:
                self._last_error = 'offline?'
            return False, 'network error', None, None

    def _find_gist(self, headers):
        import requests
        r = requests.get(f'{_API}/gists?per_page=100', headers=headers,
                         timeout=_TIMEOUT)
        self._check(r)
        ours = [g for g in r.json() if g.get('description') == GIST_MARKER]
        if not ours:
            return ''
        # Two devices racing at first setup can create two gists; everyone
        # converging on the OLDEST one keeps them in agreement forever.
        ours.sort(key=lambda g: g.get('created_at') or '')
        return ours[0].get('id') or ''

    def _create_gist(self, headers, device_id, device_name):
        import requests
        with self._lock:
            payload = json.dumps({'device': device_name,
                                  'days': self._data['days']}, indent=1)
        r = requests.post(f'{_API}/gists', headers=headers, timeout=_TIMEOUT,
                          json={'description': GIST_MARKER, 'public': False,
                                'files': {f'ytm-stats-{device_id}.json':
                                          {'content': payload}}})
        self._check(r)
        return r.json().get('id') or ''

    @staticmethod
    def _check(r):
        if r.status_code == 401:
            raise _AuthError()
        if r.status_code in (403, 429) and r.headers.get('x-ratelimit-remaining') == '0':
            raise _RateLimited()
        r.raise_for_status()


class _AuthError(Exception):
    pass


class _RateLimited(Exception):
    pass


def fmt_mins(seconds):
    """1234 -> '20m', 9876 -> '2h 44m' (whole minutes; '0m' floor)."""
    mins = int(seconds // 60)
    if mins < 60:
        return f'{mins}m'
    return f'{mins // 60}h {mins % 60:02d}m'


if __name__ == '__main__':
    import tempfile
    tmp = os.path.join(tempfile.mkdtemp(), 'stats-test.json')
    s = StatsStore(tmp)
    s.add(90)
    s.add(30)
    s.flush()
    s2 = StatsStore(tmp)
    assert s2.totals()['today'] == 120.0, s2.totals()
    # Merged view with a fake remote device + our own stale remote copy.
    today = _today()
    s2._data['remote'] = {
        'me': {'device': 'local-old', 'days': {today: 500.0}},   # our own, ahead
        'phone': {'device': 'iPhone', 'days': {today: 60.0}},
    }
    merged = dict(s2.merged_days(1, own_device_id='me'))
    assert merged[today] == 560.0, merged      # max(120,500) + 60
    devs = dict(s2.per_device(own_device_id='me', own_device_name='mac'))
    assert devs == {'mac': 500.0, 'iPhone': 60.0}, devs
    assert fmt_mins(120) == '2m' and fmt_mins(9876) == '2h 44m'
    assert len(_day_keys(7)) == 7 and _day_keys(7)[-1] == today
    print('stats.py self-test OK')
