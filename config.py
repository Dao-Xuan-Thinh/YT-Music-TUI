"""
config.py — Settings persistence (JSON file next to the script).
"""

import json
import os

_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

_DEFAULTS = {
    'cookies_file':  '',        # yt-dlp/mpv STREAMING cookies (age-restricted), via Settings (s)
    'auth_cookies_file': '',    # ytmusicapi ACCOUNT cookies (personalization), via Account (g)
    'volume':        80,
    'search_source': 'ytm',   # 'ytm', 'yt', 'both'
    'max_results':   15,
    'local_folder':  '',
    'theme':         'tokyo-night',
    'app_mode':      'online',  # 'online' or 'offline' — remembered across runs
    # Active auth method for ytmusicapi: 'none' | 'cookies' | 'browser'.
    # ('oauth' is still *accepted* here so an old config loads; boot migrates it
    # to 'none' — the OAuth backend itself was removed, YouTube rejects it.)
    'auth_method':         'none',
    # For method='browser': yt-dlp browser name + optional profile dir (live cookies,
    # re-read each launch so the session never goes stale). See Account (g).
    'auth_browser':         '',
    'auth_browser_profile': '',
    # Display name of the signed-in account (shown in the footer). Cached from
    # get_account_info() at sign-in / first boot so the footer needs no network.
    'account_name':        '',
    # Listen-time stats sync (see stats.py). The token is a GitHub PAT (classic
    # with `gist` scope, or fine-grained with Gists: read & write) — stored in
    # plaintext here; config.json is gitignored and local-only.
    'stats_token':         '',
    'stats_gist_id':       '',   # cached; rediscovered by marker on 404
    'stats_device_id':     '',   # uuid4, minted on first boot
    'stats_device_name':   '',   # shown in per-device totals (default: hostname)
    # Unix time of the last successful live account verification. Boot skips
    # the (3-5s, network) re-verify while this is fresh — the browser-jar
    # re-read still happens lazily, and feed errors still surface expiry.
    'auth_verified_ts':    0.0,
}


def _expand(path):
    """Expand ~ and environment variables in a user-supplied path."""
    if not path:
        return ''
    return os.path.expanduser(os.path.expandvars(path))


class Config:
    def __init__(self):
        self._data = dict(_DEFAULTS)
        self.load()

    def load(self):
        if os.path.isfile(_CONFIG_FILE):
            try:
                with open(_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                for key in _DEFAULTS:
                    if key in saved:
                        self._data[key] = saved[key]
            except Exception:
                pass

    def save(self):
        try:
            with open(_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2)
        except Exception as exc:
            raise RuntimeError(f'Could not save config: {exc}') from exc

    def update(self, **kwargs):
        """Set one or more values WITHOUT writing to disk (call flush() later).

        Lets the app coalesce rapid changes (volume +/- spam, theme cycling) into
        a single write instead of one disk write per keypress.
        """
        for key, value in kwargs.items():
            if key in _DEFAULTS:
                self._data[key] = value

    def flush(self):
        """Persist any pending in-memory changes."""
        self.save()

    # ── Accessors ─────────────────────────────────────────────────────────

    @property
    def cookies_file(self):
        return self._data['cookies_file']

    @cookies_file.setter
    def cookies_file(self, path):
        self._data['cookies_file'] = path or ''
        self.save()

    @property
    def volume(self):
        return int(self._data['volume'])

    @volume.setter
    def volume(self, v):
        self._data['volume'] = max(0, min(100, int(v)))
        self.save()

    @property
    def search_source(self):
        return self._data['search_source']

    @search_source.setter
    def search_source(self, v):
        if v in ('ytm', 'yt', 'both'):
            self._data['search_source'] = v
            self.save()

    @property
    def max_results(self):
        return int(self._data['max_results'])

    @property
    def local_folder(self):
        return self._data['local_folder']

    @local_folder.setter
    def local_folder(self, path):
        self._data['local_folder'] = path or ''
        self.save()

    @property
    def auth_cookies_file(self):
        return self._data.get('auth_cookies_file', '')

    @auth_cookies_file.setter
    def auth_cookies_file(self, path):
        self._data['auth_cookies_file'] = path or ''
        self.save()

    @property
    def account_name(self):
        return self._data.get('account_name', '')

    @account_name.setter
    def account_name(self, name):
        self._data['account_name'] = name or ''
        self.save()

    @property
    def stats_token(self):
        return self._data.get('stats_token', '')

    @stats_token.setter
    def stats_token(self, value):
        self._data['stats_token'] = value or ''
        self.save()

    @property
    def stats_gist_id(self):
        return self._data.get('stats_gist_id', '')

    @stats_gist_id.setter
    def stats_gist_id(self, value):
        self._data['stats_gist_id'] = value or ''
        self.save()

    @property
    def stats_device_id(self):
        return self._data.get('stats_device_id', '')

    @stats_device_id.setter
    def stats_device_id(self, value):
        self._data['stats_device_id'] = value or ''
        self.save()

    @property
    def stats_device_name(self):
        return self._data.get('stats_device_name', '')

    @stats_device_name.setter
    def stats_device_name(self, value):
        self._data['stats_device_name'] = value or ''
        self.save()

    @property
    def auth_verified_ts(self):
        try:
            return float(self._data.get('auth_verified_ts') or 0)
        except (TypeError, ValueError):
            return 0.0

    @auth_verified_ts.setter
    def auth_verified_ts(self, ts):
        self._data['auth_verified_ts'] = float(ts or 0)
        self.save()

    @property
    def app_mode(self):
        return self._data.get('app_mode') if self._data.get('app_mode') in ('online', 'offline') else 'online'

    @app_mode.setter
    def app_mode(self, mode):
        if mode in ('online', 'offline'):
            self._data['app_mode'] = mode
            self.save()

    @property
    def auth_method(self):
        # 'oauth' still read back so an old config triggers the boot migration.
        m = self._data.get('auth_method', 'none')
        return m if m in ('none', 'oauth', 'cookies', 'browser') else 'none'

    @auth_method.setter
    def auth_method(self, value):
        if value in ('none', 'cookies', 'browser'):
            self._data['auth_method'] = value
            self.save()

    @property
    def auth_browser(self):
        return self._data.get('auth_browser', '')

    @auth_browser.setter
    def auth_browser(self, value):
        self._data['auth_browser'] = value or ''
        self.save()

    @property
    def auth_browser_profile(self):
        return self._data.get('auth_browser_profile', '')

    @auth_browser_profile.setter
    def auth_browser_profile(self, value):
        self._data['auth_browser_profile'] = value or ''
        self.save()

    @property
    def theme(self):
        """Theme name as stored. Not validated against BUILTIN_THEMES here because
        the app also registers custom themes at startup (which aren't in that set);
        the App-level setter falls back gracefully if a name is truly unknown."""
        return self._data.get('theme') or _DEFAULTS['theme']

    @theme.setter
    def theme(self, name):
        if name:
            self._data['theme'] = name
            self.save()

    def valid_cookies(self):
        """Return cookies_file path (expanded) if the file exists, else empty string."""
        cf = _expand(self.cookies_file)
        return cf if (cf and os.path.isfile(cf)) else ''

    def valid_auth_cookies(self):
        """Return auth_cookies_file path (expanded) if the file exists, else ''."""
        cf = _expand(self.auth_cookies_file)
        return cf if (cf and os.path.isfile(cf)) else ''


if __name__ == '__main__':
    cfg = Config()
    print('Loaded config:')
    for k, v in cfg._data.items():
        print(f'  {k}: {v!r}')

    # Round-trip test
    cfg.volume = 75
    cfg.search_source = 'both'
    cfg.update(volume=42)       # in-memory only
    cfg.flush()                 # now persisted
    cfg.save()

    cfg2 = Config()
    assert cfg2.volume == 42, cfg2.volume
    assert cfg2.search_source == 'both'
    print('\nRound-trip OK (incl. update/flush). config.json written.')
