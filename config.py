"""
config.py — Settings persistence (JSON file next to the script).
"""

import json
import os

_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

_DEFAULTS = {
    'cookies_file':  '',
    'volume':        80,
    'search_source': 'ytm',   # 'ytm', 'yt', 'both'
    'max_results':   15,
    'local_folder':  '',
    'theme':         'tokyo-night',
    'app_mode':      'online',  # 'online' or 'offline' — remembered across runs
    # YouTube OAuth client (device flow). The token itself lives in oauth.json;
    # these are your Google Cloud OAuth client credentials, needed again at
    # client construction for token refresh. See YOUTUBE_LOGIN.md.
    'oauth_client_id':     '',
    'oauth_client_secret': '',
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
    def app_mode(self):
        return self._data.get('app_mode') if self._data.get('app_mode') in ('online', 'offline') else 'online'

    @app_mode.setter
    def app_mode(self, mode):
        if mode in ('online', 'offline'):
            self._data['app_mode'] = mode
            self.save()

    @property
    def oauth_client_id(self):
        return self._data.get('oauth_client_id', '')

    @oauth_client_id.setter
    def oauth_client_id(self, value):
        self._data['oauth_client_id'] = value or ''
        self.save()

    @property
    def oauth_client_secret(self):
        return self._data.get('oauth_client_secret', '')

    @oauth_client_secret.setter
    def oauth_client_secret(self, value):
        self._data['oauth_client_secret'] = value or ''
        self.save()

    @property
    def theme(self):
        """Theme name, validated against Textual's built-in themes."""
        name = self._data.get('theme') or _DEFAULTS['theme']
        try:
            from textual.theme import BUILTIN_THEMES
            if name not in BUILTIN_THEMES:
                return _DEFAULTS['theme']
        except Exception:
            pass
        return name

    @theme.setter
    def theme(self, name):
        if name:
            self._data['theme'] = name
            self.save()

    def valid_cookies(self):
        """Return cookies_file path (expanded) if the file exists, else empty string."""
        cf = _expand(self.cookies_file)
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
