"""
youtube.py — YouTube / YouTube Music wrapper.

YouTube Music (search + playlists) goes through ytmusicapi, which paginates
large playlists fully via YTM's own continuation API and returns artist/album
metadata natively. (yt-dlp's flat playlist extraction caps YTM playlists at
~108 entries — an upstream bug — and provides no artist for flat entries.)
Regular YouTube search/URLs and all audio streaming stay on yt-dlp/mpv.
"""

import os
import threading
import urllib.parse
import yt_dlp


class _SilentLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


# ── ytmusicapi (YouTube Music) ────────────────────────────────────────────────

# NOTE: OAuth (device-flow) auth was removed entirely — YouTube rejects
# third-party-client OAuth tokens with HTTP 400 on every youtubei call (verified
# empirically; no client-side fix). Browser / cookies auth below is what works.

_ytm = None
_auth_method = 'none'        # 'none' | 'cookies' | 'browser'
_cookies_file = ''
_auth_browser = ''           # yt-dlp browser name for method='browser' (live cookies)
_auth_browser_profile = ''   # optional profile dir/name for that browser
_authed = False              # cached auth state (avoids re-parsing cookies per call)

# Serializes ALL ytmusicapi access. A YTMusic client wraps a single requests.Session
# with mutable per-request state (SAPISIDHASH, headers, innertube context); calling it
# from two threads at once (e.g. the boot For-You feed load AND the auth verify) can
# corrupt a response (spurious parse errors → false "logged out") or deadlock inside
# urllib3's connection pool — the cause of the post-sign-in hang. Reentrant so a wrapped
# call may nest _get_ytm(). Only ever held by daemon threads, never the UI thread.
_ytm_lock = threading.RLock()

# Hard cap on every ytmusicapi HTTP request. ytmusicapi/requests default to NO timeout,
# so a half-open / black-holed YouTube connection makes a call (client build,
# get_account_info, get_home, search) block forever — and because those calls run under
# _ytm_lock, one stalled call would wedge every later one. A bounded timeout turns that
# into a normal exception the callers already handle (verify→unknown, feed→fallback,
# cookies_auth_ok→error message), so the app can never permanently hang on the network.
_HTTP_TIMEOUT = 20  # seconds


class _TimeoutSession:
    """Factory for a requests.Session whose every request carries a default timeout."""
    def __new__(cls):
        import requests

        class _S(requests.Session):
            def request(self, *args, **kwargs):
                kwargs.setdefault('timeout', _HTTP_TIMEOUT)
                return super().request(*args, **kwargs)

        return _S()


def _new_ytm(**kwargs):
    """Build a YTMusic with a timeout-bounded session (each client gets its own)."""
    from ytmusicapi import YTMusic
    return YTMusic(requests_session=_TimeoutSession(), **kwargs)


def configure_auth(method='none', cookies_file='', browser='', profile=''):
    """Set the active auth method + its inputs and drop the cached client so the
    next _get_ytm() rebuilds. method: 'none' | 'cookies' | 'browser'."""
    global _auth_method, _cookies_file, _ytm, _authed
    global _auth_browser, _auth_browser_profile
    _auth_method = method if method in ('none', 'cookies', 'browser') else 'none'
    _cookies_file = os.path.expanduser(os.path.expandvars(cookies_file or ''))
    _auth_browser = browser or ''
    _auth_browser_profile = profile or ''
    _ytm = None
    # Evaluate auth validity ONCE here and cache it; the footer/status query
    # is_authenticated() often and a per-call cookie reparse / extraction would
    # stall the UI.
    if _auth_method == 'cookies':
        _authed = _browser_headers_from_cookies(_cookies_file) is not None
    elif _auth_method == 'browser':
        # Don't extract on the UI thread (slow / may touch a locked DB) — assume valid
        # if a browser is configured and let verify_auth_live() (daemon) confirm or
        # downgrade, exactly like cookies.
        _authed = bool(_auth_browser)
    else:
        _authed = False


# The only cookies YouTube Music's API needs for auth. A typical cookies.txt is a
# full-browser dump (hundreds of sites, plus ~95 per-tab `ST-*` session cookies);
# sending all of them makes a ~100 KB Cookie header that YouTube rejects with an
# empty body. We send just these (~2 KB).
_AUTH_COOKIE_NAMES = {
    'SAPISID', '__Secure-1PAPISID', '__Secure-3PAPISID',
    'SID', '__Secure-1PSID', '__Secure-3PSID',
    'HSID', 'SSID', 'APISID',
    '__Secure-1PSIDTS', '__Secure-3PSIDTS',
    '__Secure-1PSIDCC', '__Secure-3PSIDCC', 'SIDCC',
    'LOGIN_INFO', 'VISITOR_INFO1_LIVE', 'VISITOR_PRIVACY_METADATA',
    'YSC', 'PREF', 'CONSENT', 'SOCS', 'NID', '__Secure-YNID',
}


def _headers_from_jar(jar):
    """Build a ytmusicapi browser-auth header dict from any cookie jar.

    ytmusicapi authenticates as a web session: it reads the SAPISID from the cookie
    header and recomputes the SAPISIDHASH `authorization` on each request. We just
    need a cookie header carrying a logged-in session. Returns None if the jar has
    no SAPISID/__Secure-3PAPISID (i.e. not a logged-in YouTube session).
    """
    by_name = {}     # de-dupe by cookie name, keep insertion order (last wins)
    for ck in jar:
        if ck.name not in _AUTH_COOKIE_NAMES:
            continue   # skip ST-* / unrelated cookies → keep the header small
        if 'youtube' in (ck.domain or '') or 'google' in (ck.domain or ''):
            by_name[ck.name] = ck.value
    if not ('SAPISID' in by_name or '__Secure-3PAPISID' in by_name):
        return None
    cookie_header = '; '.join(f'{name}={value}' for name, value in by_name.items())
    return {
        'cookie': cookie_header,
        # Must contain "SAPISIDHASH" so ytmusicapi detects BROWSER auth; the real
        # value is recomputed from the cookie's SAPISID on every request.
        'authorization': 'SAPISIDHASH placeholder',
        'x-goog-authuser': '0',
        'origin': 'https://music.youtube.com',
        'user-agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/120.0 Safari/537.36'),
    }


def _browser_headers_from_cookies(path):
    """Build a ytmusicapi browser-auth header dict from a Netscape cookies file.

    Returns None if the file has no SAPISID/__Secure-3PAPISID (i.e. not a logged-in
    YouTube cookie export).
    """
    import http.cookiejar
    if not path or not os.path.isfile(path):
        return None
    try:
        jar = http.cookiejar.MozillaCookieJar(path)
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        return None
    return _headers_from_jar(jar)


def _browser_headers_live(browser, profile=''):
    """Read the CURRENT logged-in session straight from a running browser's cookie
    store (via yt-dlp) and build the ytmusicapi auth header. This is the durable
    sign-in path: re-read at every launch, so the session never goes stale while the
    browser stays logged in.

    `browser` is a yt-dlp browser name (firefox/chrome/edge/brave/…). For a
    Firefox-family browser (Firefox, Zen, LibreWolf, …) `profile` may be an absolute
    profile-directory path — yt-dlp's firefox extractor reads its cookies.sqlite.
    Returns None on any failure (no browser, locked/encrypted DB, not logged in).

    Note: Chromium browsers (Chrome/Edge/Brave) on Windows use App-Bound Encryption,
    which blocks external decryption (yt-dlp #10927) — Firefox-family works.
    """
    if not browser:
        return None
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
        jar = extract_cookies_from_browser(browser, profile or None, _SilentLogger())
    except Exception:
        return None
    return _headers_from_jar(jar)


# Firefox-family browsers (read via yt-dlp's `firefox` extractor + a profile-dir path).
# These store cookies in an unencrypted cookies.sqlite, so extraction works everywhere —
# unlike Chromium browsers, which on Windows use App-Bound Encryption (yt-dlp #10927).
# name → list of OS-specific roots that each hold per-profile subdirectories.
def _firefox_family_roots():
    home = os.path.expanduser('~')
    appdata = os.environ.get('APPDATA', os.path.join(home, 'AppData', 'Roaming'))
    support = os.path.join(home, 'Library', 'Application Support')
    # On Linux a Firefox-family browser may be native, Flatpak (sandboxed under
    # ~/.var/app/<app-id>/) or Snap (~/snap/<name>/common/), each with its own profile
    # root — so we probe all of them. (display name, [candidate profile-container roots])
    return [
        ('Firefox',   [os.path.join(appdata, 'Mozilla', 'Firefox', 'Profiles'),
                       os.path.join(support, 'Firefox', 'Profiles'),
                       os.path.join(home, '.mozilla', 'firefox'),
                       os.path.join(home, '.var', 'app', 'org.mozilla.firefox',
                                    '.mozilla', 'firefox'),
                       os.path.join(home, 'snap', 'firefox', 'common',
                                    '.mozilla', 'firefox')]),
        ('Zen',       [os.path.join(appdata, 'zen', 'Profiles'),
                       os.path.join(support, 'zen', 'Profiles'),
                       os.path.join(home, '.zen'),
                       os.path.join(home, '.var', 'app', 'app.zen_browser.zen', '.zen'),
                       os.path.join(home, 'snap', 'zen-browser', 'common', '.zen'),
                       os.path.join(home, 'snap', 'zen', 'common', '.zen')]),
        ('LibreWolf', [os.path.join(appdata, 'librewolf', 'Profiles'),
                       os.path.join(support, 'librewolf', 'Profiles'),
                       os.path.join(home, '.librewolf'),
                       os.path.join(home, '.var', 'app',
                                    'io.gitlab.librewolf-community', '.librewolf'),
                       os.path.join(home, 'snap', 'librewolf', 'common', '.librewolf')]),
        ('Waterfox',  [os.path.join(appdata, 'Waterfox', 'Profiles'),
                       os.path.join(support, 'Waterfox', 'Profiles'),
                       os.path.join(home, '.waterfox'),
                       os.path.join(home, '.var', 'app', 'net.waterfox.waterfox',
                                    '.waterfox')]),
    ]


def detect_browser_profiles():
    """Enumerate sign-in-able browser sources for the Account screen.

    Returns a list of {'label', 'browser', 'profile'} dicts:
      - every Firefox-family profile that has a cookies.sqlite (browser='firefox',
        profile=<absolute dir>), which is the path proven to work; plus
      - the common Chromium/other browsers by name (profile='') for setups where they
        aren't App-Bound-Encryption-blocked (non-Windows).
    Best-effort: any filesystem error is skipped.
    """
    out = []
    for app, roots in _firefox_family_roots():
        for root in roots:
            try:
                if not os.path.isdir(root):
                    continue
                for entry in sorted(os.listdir(root)):
                    pdir = os.path.join(root, entry)
                    if os.path.isfile(os.path.join(pdir, 'cookies.sqlite')):
                        # Firefox profile dirs look like "<id>.<name>" → show <name>.
                        disp = entry.split('.', 1)[1] if '.' in entry else entry
                        out.append({'label': f'{app} — {disp}',
                                    'browser': 'firefox', 'profile': pdir})
            except OSError:
                continue
    # Direct (default-profile) browser options for non-Firefox setups.
    for name in ('chrome', 'edge', 'brave', 'chromium', 'vivaldi', 'opera'):
        out.append({'label': f'{name.capitalize()} (default profile)',
                    'browser': name, 'profile': ''})
    return out


def is_authenticated():
    """True if the active auth method has usable credentials (cached by
    configure_auth so this is O(1) — see _authed)."""
    return _authed


def auth_status():
    """Short label for the footer/UI describing the active auth method."""
    if _auth_method == 'cookies':
        return 'cookies' if is_authenticated() else 'cookies (not set)'
    if _auth_method == 'browser':
        return 'browser' if is_authenticated() else 'browser (not set)'
    return 'public'


def _get_ytm():
    """Lazily create a YTMusic client for the active auth method. Falls back to an
    anonymous client (public data only) on any construction error. Thread-safe:
    double-checked under _ytm_lock so concurrent callers build the client exactly once."""
    global _ytm
    if _ytm is not None:
        return _ytm
    with _ytm_lock:
        if _ytm is None:
            if _auth_method == 'cookies':
                headers = _browser_headers_from_cookies(_cookies_file)
                try:
                    _ytm = _new_ytm(auth=headers) if headers else _new_ytm()
                except Exception:
                    _ytm = _new_ytm()
            elif _auth_method == 'browser':
                # Re-read the live session from the browser each launch (durable auth).
                headers = _browser_headers_live(_auth_browser, _auth_browser_profile)
                try:
                    _ytm = _new_ytm(auth=headers) if headers else _new_ytm()
                except Exception:
                    _ytm = _new_ytm()
            else:
                _ytm = _new_ytm()
    return _ytm


def _is_logged_out_error(exc):
    """True if `exc` indicates a confirmed logged-out/expired session (vs. a
    transient network failure).

    ytmusicapi reaches YouTube fine but raises a KeyError/IndexError/TypeError while
    navigating the account-less "logged out" menu (no activeAccountHeaderRenderer).
    A network failure instead raises a requests exception — that's *unknown*, not a
    confirmed logout, so we must not treat it as one.
    """
    try:
        import requests
        if isinstance(exc, requests.exceptions.RequestException):
            return False
    except Exception:
        pass
    return isinstance(exc, (KeyError, IndexError, TypeError))


def cookies_auth_ok(cookies_file):
    """Validate a cookies file by fetching the signed-in account.

    Returns (ok: bool, message): on success message is the account name; on failure
    it's the reason. Uses get_account_info() (not get_library_playlists, which
    returns [] for unauthenticated sessions instead of failing).
    """
    headers = _browser_headers_from_cookies(
        os.path.expanduser(os.path.expandvars(cookies_file or '')))
    if headers is None:
        return False, ('no logged-in YouTube cookies found in that file '
                       '(need SAPISID / __Secure-3PAPISID)')
    try:
        with _ytm_lock:
            info = _new_ytm(auth=headers).get_account_info() or {}
        name = info.get('accountName')
        if name:
            return True, name
        return False, ('cookies are expired or logged out — re-export cookies.txt '
                       'while signed in to music.youtube.com')
    except Exception as exc:
        if _is_logged_out_error(exc):
            return False, ('cookies are expired or logged out — re-export cookies.txt '
                           'while signed in to music.youtube.com')
        return False, f'{type(exc).__name__}: {exc}'


def verify_auth_live():
    """Live-validate the active session and report the result. Network call — run
    from a daemon thread, never the UI hot path.

    Returns (status, name):
      ('ok', name)      — signed in; `name` is the account display name.
      ('expired', '')   — COOKIE auth confirmed logged out (empty account or a
                          logged-out parse error); downgrades is_authenticated().
      ('unknown', '')   — couldn't confirm (network/transient error); auth state
                          left untouched so a blip doesn't drop it.
    """
    global _authed
    if not _authed:
        return ('unknown', '')
    try:
        with _ytm_lock:
            info = _get_ytm().get_account_info() or {}
        name = info.get('accountName') or ''
        if name:
            return ('ok', name)
        if _auth_method in ('cookies', 'browser'):
            _authed = False
            return ('expired', '')
        return ('unknown', '')
    except Exception as exc:
        if _auth_method in ('cookies', 'browser') and _is_logged_out_error(exc):
            _authed = False
            return ('expired', '')
        return ('unknown', '')


def _parse_home(data):
    """Map a ytmusicapi get_home() response into our section/item shape.

    Returns [{'title': str, 'items': [...]}] where each item is either
    {'kind': 'song', 'track': <track dict>} or
    {'kind': 'playlist', 'name': str, 'playlistId': str}. Empty sections dropped.
    """
    sections = []
    for sec in data:
        if not isinstance(sec, dict):
            continue
        items = []
        for c in (sec.get('contents') or []):
            if not isinstance(c, dict):
                continue   # YTM occasionally returns a null entry in a section
            if c.get('videoId'):
                items.append({'kind': 'song', 'track': _ytm_track_to_dict(c)})
            elif c.get('playlistId'):
                items.append({'kind': 'playlist',
                              'name': c.get('title') or 'Playlist',
                              'playlistId': c['playlistId']})
        if items:
            sections.append({'title': sec.get('title') or '', 'items': items})
    return sections


def ytm_home(limit=3):
    """The YouTube Music home feed (personalized when authenticated).

    If the *network call* fails while authenticated we retry inside as_mobile()
    (ANDROID_MUSIC context). Parsing happens outside the try so a parser error
    never triggers the mobile retry — that retry rejects cookie auth with 400.
    """
    yt = _get_ytm()
    with _ytm_lock:
        try:
            data = yt.get_home(limit=limit)
        except Exception:
            if is_authenticated() and hasattr(yt, 'as_mobile'):
                with yt.as_mobile():
                    data = yt.get_home(limit=limit)
            else:
                raise
    return _parse_home(data)


def ytm_home_public(limit=3):
    """The generic (anonymous) home feed — fallback when a signed-in user's
    personalized feed errors, so the For You tab still shows something."""
    with _ytm_lock:
        data = _new_ytm().get_home(limit=limit)
    return _parse_home(data)


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
    with _ytm_lock:
        data = _get_ytm().get_playlist(playlist_id, limit=limit)
    return [
        _ytm_track_to_dict(t)
        for t in data.get('tracks', [])
        if t.get('videoId')
    ]


def ytm_search(query, max_results=15):
    """Search YouTube Music for songs via ytmusicapi. Returns list of track dicts."""
    with _ytm_lock:
        results = _get_ytm().search(query, filter='songs', limit=max_results)
    out = [_ytm_track_to_dict(t) for t in results if t.get('videoId')]
    return out[:max_results]


def _thumb(d):
    thumbs = d.get('thumbnails') or []
    return thumbs[-1]['url'] if thumbs else ''


def ytm_search_entities(query, max_results=15):
    """Top artist/album matches (NO songs) — used to enrich keyword search with an artist
    entry + a few albums. Returns {'artists': [{name, channelId, thumbnail}],
    'albums': [{name, browseId, kind, thumbnail, artist}]}.

    Uses the *filtered* searches (filter='artists'/'albums'). The UNFILTERED search ranks
    artists badly — e.g. "Ado" returns a malformed empty entry then a tiny 5-subscriber
    "ADO" channel before the real 9M-subscriber Ado — so we query each type directly.
    """
    out = {'artists': [], 'albums': []}
    try:
        with _ytm_lock:
            ares = _get_ytm().search(query, filter='artists', limit=5)
        for r in ares:
            if r.get('browseId'):
                out['artists'].append({'name': r.get('artist') or r.get('title') or '',
                                       'channelId': r['browseId'], 'thumbnail': _thumb(r)})
    except Exception:
        pass
    try:
        with _ytm_lock:
            alres = _get_ytm().search(query, filter='albums', limit=6)
        for r in alres:
            if r.get('browseId'):
                out['albums'].append({
                    'name': r.get('title') or '', 'browseId': r['browseId'],
                    'kind': r.get('resultType') or 'album', 'thumbnail': _thumb(r),
                    'artist': ', '.join(a.get('name', '') for a in (r.get('artists') or [])
                                        if a.get('name'))})
    except Exception:
        pass

    def _dedupe(items, key):
        seen, o = set(), []
        for it in items:
            k = it.get(key)
            if k and k not in seen:
                seen.add(k)
                o.append(it)
        return o
    out['artists'] = _dedupe(out['artists'], 'channelId')[:3]
    out['albums'] = _dedupe(out['albums'], 'browseId')[:6]
    return out


def ytm_search_all(query, max_results=15):
    """Richer search: songs (via the songs filter) + artist/album entities. Returns
    {'songs': [track], 'artists': [...], 'albums': [...]}."""
    out = {'songs': []}
    try:
        out['songs'] = ytm_search(query, max_results=max_results)
    except Exception:
        pass
    out.update(ytm_search_entities(query, max_results=max_results))
    return out


def ytm_artist(channel_id):
    """Artist page → {name, subscribers, thumbnail, sections}. Each section is
    {title, kind, items}; song/video items are track dicts, album/single items are
    {'kind':'album','name','browseId','thumbnail','year'} (opened via ytm_album)."""
    with _ytm_lock:
        a = _get_ytm().get_artist(channel_id)
    sections = []
    for key, title in (('songs', 'Songs'), ('albums', 'Albums'),
                       ('singles', 'Singles'), ('videos', 'Videos')):
        block = a.get(key)
        if not isinstance(block, dict):
            continue
        items = []
        for r in (block.get('results') or []):
            if not isinstance(r, dict):
                continue
            if r.get('videoId'):
                items.append(_ytm_track_to_dict(r))
            elif r.get('browseId'):
                items.append({'kind': 'album', 'name': r.get('title') or '',
                              'browseId': r['browseId'], 'thumbnail': _thumb(r),
                              'year': r.get('year') or ''})
        if items:
            sections.append({'title': title, 'kind': key, 'items': items})
    return {'name': a.get('name') or '', 'subscribers': a.get('subscribers') or '',
            'thumbnail': _thumb(a), 'sections': sections}


def ytm_album(browse_id):
    """Album tracks (via get_album) → list of track dicts."""
    with _ytm_lock:
        data = _get_ytm().get_album(browse_id)
    return [_ytm_track_to_dict(t) for t in (data.get('tracks') or []) if t.get('videoId')]


def ytm_radio(video_id, limit=25):
    """Endless mix seeded from a track (get_watch_playlist radio) → list of track dicts."""
    with _ytm_lock:
        data = _get_ytm().get_watch_playlist(videoId=video_id, radio=True, limit=limit)
    out = []
    for t in (data.get('tracks') or []):
        if not t.get('videoId'):
            continue
        if 'duration' not in t and t.get('length'):
            t = dict(t)
            t['duration'] = t['length']   # watch-playlist tracks carry 'length' (M:SS)
        out.append(_ytm_track_to_dict(t))
    return out


def ytm_lyrics(video_id):
    """Lyrics for a video, or None if unavailable. Requests timestamps so playback can
    follow along when the song has synced lyrics.

    Returns {'synced': bool, 'lines': [{'text','start','end'}], 'text': str, 'source': str}.
    `start`/`end` are milliseconds (0 when not synced). `text` is the joined plain lyrics.
    """
    # Use an ANONYMOUS client: get_lyrics(timestamps=True) runs inside as_mobile()
    # (ANDROID_MUSIC context), which rejects cookie/browser auth with HTTP 400. Lyrics are
    # public, so a signed-out client works for everyone. Fall back to plain if timestamped
    # lyrics can't be fetched.
    try:
        with _ytm_lock:
            yt = _new_ytm()
            wp = yt.get_watch_playlist(videoId=video_id, limit=1)
            bid = wp.get('lyrics')
            if not bid:
                return None
            try:
                lyr = yt.get_lyrics(bid, timestamps=True)
            except Exception:
                lyr = yt.get_lyrics(bid, timestamps=False)
    except Exception:
        return None
    if not lyr:
        return None

    def _g(obj, k):
        return obj.get(k) if isinstance(obj, dict) else getattr(obj, k, None)

    source = _g(lyr, 'source') or ''
    if _g(lyr, 'hasTimestamps'):
        lines = []
        for ln in (_g(lyr, 'lyrics') or []):
            lines.append({'text': _g(ln, 'text') or '',
                          'start': int(_g(ln, 'start_time') or 0),
                          'end': int(_g(ln, 'end_time') or 0)})
        if lines:
            return {'synced': True, 'lines': lines,
                    'text': '\n'.join(l['text'] for l in lines), 'source': source}
    # Plain lyrics (no timing).
    text = _g(lyr, 'lyrics')
    if not isinstance(text, str) or not text:
        return None
    lines = [{'text': t, 'start': 0, 'end': 0} for t in text.split('\n')]
    return {'synced': False, 'lines': lines, 'text': text, 'source': source}


def translate_text(text, target='en'):
    """Translate a whole block of text to `target` in ONE request (free Google endpoint).
    Newlines are preserved, so the caller can split the result back into per-line
    translations aligned with the original. Returns '' on failure."""
    if not text:
        return ''
    try:
        import requests
        params = {'client': 'gtx', 'sl': 'auto', 'tl': target, 'dt': 't', 'q': text}
        r = requests.get('https://translate.googleapis.com/translate_a/single',
                         params=params, timeout=_HTTP_TIMEOUT)
        data = r.json()
        return ''.join(seg[0] for seg in data[0] if seg and seg[0])
    except Exception:
        return ''


def _ydl_opts(cookies_file=None, extra=None):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'logger': _SilentLogger(),
        # Bound the network so a stalled connection can't hang extraction forever
        # (a stuck fetch otherwise wedges playback until the app restarts).
        'socket_timeout': 15,
        'retries': 1,
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


def resolve(inp, source='ytm', cookies_file=None, max_results=15):
    """
    Smart entry point: URL (video/playlist) or keyword search.
    Always returns a list of track dicts.
    """
    if not _is_url(inp):
        return search(inp, source=source, max_results=max_results,
                      cookies_file=cookies_file)

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
