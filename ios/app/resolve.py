"""App-side YouTube resolver for the embedded-Python iOS spike.

Mirrors the desktop `youtube._entry_to_dict` track shape and forces an m4a/AAC
format for AVPlayer. JS challenges are solved on-device by the JavaScriptCore
provider (`ios_jsc_provider`), registered on import.
"""
from __future__ import annotations

import collections
import json
import os
import sys
import time

# ── Debug log (ring buffer, read by the Settings debug screen via get_log) ────
_LOG = collections.deque(maxlen=400)


def _log(tag: str, msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} [{tag}] {msg}"
    _LOG.append(line)
    print(line, flush=True)


def get_log(_: str = "") -> str:
    """The recent engine log as plain text (newest last)."""
    return "\n".join(_LOG)

# Use certifi's CA bundle for TLS (iOS has no OpenSSL default cert path).
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except Exception:
    pass

import ios_jsc_provider  # noqa: F401  registers JavaScriptCoreJCP
import yt_dlp

_M4A_FORMAT = "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio"
# Fast clients that return progressive m4a without the slow web-client JS challenge.
# (JavaScriptCore JS solving still works as the fallback if 'web' is ever needed.)
_PLAYER_CLIENTS = ["android_vr", "ios", "android"]

# ── Account auth (ytmusicapi browser session) ─────────────────────────────────
# Mirrors the desktop youtube.py: ytmusicapi authenticates as a web session — it reads
# SAPISID from the cookie header and recomputes the SAPISIDHASH `authorization` per request,
# so we only need a cookie header carrying a logged-in session. Set from the iOS app
# (WebView capture or pasted cookies) via set_auth(); used by every YTMusic() build.
_AUTH_COOKIE_NAMES = {
    "SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID",
    "SID", "__Secure-1PSID", "__Secure-3PSID",
    "HSID", "SSID", "APISID",
    "__Secure-1PSIDTS", "__Secure-3PSIDTS",
    "__Secure-1PSIDCC", "__Secure-3PSIDCC", "SIDCC",
    "LOGIN_INFO", "VISITOR_INFO1_LIVE", "VISITOR_PRIVACY_METADATA",
    "YSC", "PREF", "CONSENT", "SOCS", "NID", "__Secure-YNID",
}
_auth_headers = None   # set by set_auth()


def _headers_from_cookie_str(cookie_str):
    """Build a ytmusicapi browser-auth header dict from a raw 'k=v; k=v' cookie string.
    Returns None unless it carries a logged-in session (SAPISID / __Secure-3PAPISID)."""
    by_name = {}
    for part in (cookie_str or "").split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name in _AUTH_COOKIE_NAMES:
            by_name[name] = value.strip()
    if not ("SAPISID" in by_name or "__Secure-3PAPISID" in by_name):
        return None
    return {
        "cookie": "; ".join(f"{n}={v}" for n, v in by_name.items()),
        "authorization": "SAPISIDHASH placeholder",   # ytmusicapi recomputes the real value
        "x-goog-authuser": "0",
        "origin": "https://music.youtube.com",
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    }


def _ytm():
    """A YTMusic client — authenticated if a session is set, else anonymous."""
    from ytmusicapi import YTMusic
    if _auth_headers:
        try:
            return YTMusic(auth=_auth_headers)
        except Exception:
            pass
    return YTMusic()


def _ytm_try(call):
    """Run call(yt) with the session client; if that fails while signed in, retry
    anonymously. A stale/expired session (YouTube answers 401 or a logged-out shape)
    must degrade the app to anonymous — never break search/home/artist outright."""
    from ytmusicapi import YTMusic
    try:
        return call(_ytm())
    except Exception as e:
        if not _auth_headers:
            raise
        _log("auth", f"signed-in call failed ({type(e).__name__}: {str(e)[:120]}) — retrying anonymously")
        return call(YTMusic())


_cookiefile = None   # Netscape cookies.txt built from the account cookies (for yt-dlp)


def _write_cookiefile():
    """Serialize the account auth cookies to a Netscape cookies.txt for yt-dlp
    (it has no cookie-from-string option). Refreshed on every set_auth(); the
    premium retry in resolve() is the only consumer."""
    global _cookiefile
    _cookiefile = None
    if not _auth_headers:
        return
    import tempfile
    path = os.path.join(tempfile.gettempdir(), "ytm_account_cookies.txt")
    try:
        exp = str(int(time.time()) + 365 * 24 * 3600)
        rows = ["# Netscape HTTP Cookie File"]
        for part in _auth_headers["cookie"].split("; "):
            name, _, value = part.partition("=")
            if not name or not value:
                continue
            # The session cookies ride on both domains; write each for both.
            for domain in (".youtube.com", ".google.com"):
                rows.append("\t".join([domain, "TRUE", "/", "TRUE", exp, name, value]))
        with open(path, "w") as f:
            f.write("\n".join(rows) + "\n")
        _cookiefile = path
    except Exception:
        _cookiefile = None


def set_auth(cookie_str: str = "") -> str:
    """Set (or clear, with "") the account session from a cookie string. Returns JSON
    {ok, name, reason} — reason is "" on success, "no_session" when the string carries
    no login cookies, "expired" when they exist but YouTube rejects them. A session
    that fails verification is NOT left armed (it would 401 every ytmusicapi call)."""
    global _auth_headers
    h = _headers_from_cookie_str(cookie_str)
    if not h:
        _auth_headers = None
        _write_cookiefile()
        _log("auth", "signed out" if not cookie_str else "cookie string carries no login session")
        return json.dumps({"ok": False, "name": "", "reason": "no_session"})
    try:
        from ytmusicapi import YTMusic
        info = YTMusic(auth=h).get_account_info() or {}
        name = info.get("accountName") or ""
    except Exception as e:
        _auth_headers = None
        _write_cookiefile()
        _log("auth", f"session verification failed ({type(e).__name__}: {str(e)[:120]}) — staying anonymous")
        return json.dumps({"ok": False, "name": "", "reason": "expired"})
    _auth_headers = h
    _write_cookiefile()
    _log("auth", f"signed in as {name!r}" if name else "verification returned no account name")
    return json.dumps({"ok": bool(name), "name": name,
                       "reason": "" if name else "expired"})


def _entry_to_dict(e: dict) -> dict:
    vid = e.get("id") or ""
    url = e.get("webpage_url") or e.get("url") or (
        f"https://www.youtube.com/watch?v={vid}" if vid else "")
    return {
        "id": vid,
        "title": e.get("title") or "Unknown",
        "uploader": e.get("artist") or e.get("uploader") or e.get("channel") or "",
        "duration": int(e.get("duration") or 0),
        "url": url,                       # canonical watch URL
        "stream_url": e.get("url") or "", # direct m4a stream for AVPlayer
        "ext": e.get("ext"),
        "acodec": e.get("acodec"),
        "abr": e.get("abr"),
        "thumbnail": e.get("thumbnail") or "",
    }


def _probe_jsc(url: str) -> dict:
    """Force the `web` client (requires n-sig + signature JS solving) so the
    JavaScriptCore provider must run. Returns proof that solving worked on-device."""
    log = []

    class L:
        def debug(self, m):
            if any(k in m for k in ("Solving JS challenges", "JS Challenge Providers",
                                    "JavaScriptCore", "n challenge", "Signature")):
                log.append(m)
        info = debug
        def warning(self, m):
            if "solving failed" in m or "challenge" in m.lower():
                log.append("WARN: " + m)
        def error(self, m):
            log.append("ERR: " + m)

    opts = {
        "skip_download": True, "format": _M4A_FORMAT, "verbose": True, "logger": L(),
        "extractor_args": {"youtube": {"player_client": ["web"]}},
    }
    out = {"forced_client": "web"}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        su = info.get("url", "")
        out["web_stream_ok"] = bool(su and "googlevideo" in su)
        out["solved_by_jsc"] = any("using JavaScriptCore" in m for m in log)
        out["solve_failed"] = any("solving failed" in m for m in log)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    out["log"] = [m[:160] for m in log][:8]
    return out


# While set (unix time), resolve() tries the default web/tv clients BEFORE the
# anonymous mobile ones: armed for 30 min whenever the mobile path just failed
# retriably or a resolved URL 403'd during playback (PO-token enforcement makes
# anonymous mobile URLs extract fine yet die at the CDN — keep minting them and
# every track stalls 8-48s or worse). A second arm in one app session means the
# enforcement is chronic, not a blip — latch for the rest of the session.
_prefer_default_until = 0.0
_latch_arms = 0
_LATCH_SECONDS = 1800

# Videos confirmed unavailable (removed/private/region-blocked): NO client can
# ever resolve them, so cache the verdict briefly and answer repeat attempts
# instantly instead of burning ~8s of network per tap.
_dead_ids = {}          # video id -> verdict expiry (unix time)
_DEAD_TTL = 600

_UNAVAILABLE_MARKERS = (
    "video is not available", "video unavailable", "private video",
    "has been removed", "account associated with this video has been terminated",
)


def _is_unavailable(err: str) -> bool:
    low = err.lower()
    return any(m in low for m in _UNAVAILABLE_MARKERS)


def _vid_of(url: str) -> str:
    if "watch?v=" in url:
        return url.split("watch?v=")[-1].split("&")[0]
    return "" if url.startswith("http") else url


def _err_json(msg: str) -> str:
    """Failure result in the FULL track shape — Swift's Track decoder requires
    every field, so a bare {_ok,_error} dict never decodes and the UI could only
    show a generic message instead of the real reason."""
    return json.dumps({
        "id": "", "title": "", "uploader": "", "duration": 0,
        "url": "", "stream_url": "", "thumbnail": "",
        "_ok": False, "_error": msg,
    })


def _mark_dead(url: str) -> None:
    vid = _vid_of(url)
    if vid:
        _dead_ids[vid] = time.time() + _DEAD_TTL
        _log("resolve", f"{vid} marked unavailable for {_DEAD_TTL // 60} min")


def _known_dead(url: str) -> bool:
    vid = _vid_of(url)
    return bool(vid) and _dead_ids.get(vid, 0) > time.time()


def _base_opts():
    return {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "format": _M4A_FORMAT,
        # Bound the network so a stalled connection can't hang the resolve forever (a stuck
        # fetch otherwise starves later resolves under the GIL until the app restarts).
        "socket_timeout": 15,
        "retries": 1,
    }


def _extract(url, opts, t0, tag):
    """One yt-dlp extraction → track-dict JSON. Raises on failure."""
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    d = _entry_to_dict(info)
    d["_elapsed_s"] = round(time.time() - t0, 2)
    d["_ok"] = bool(d["stream_url"] and "googlevideo" in d["stream_url"])
    _log("resolve", f"{d['id']} [{tag}] ok={d['_ok']} in {d['_elapsed_s']}s "
                    f"({d.get('ext')}/{d.get('abr')}kbps)")
    return json.dumps(d)


def _extract_mobile(url, t0):
    """Fast anonymous path: mobile clients, direct m4a, no JS challenges."""
    opts = _base_opts()
    opts["extractor_args"] = {"youtube": {"player_client": _PLAYER_CLIENTS}}
    return _extract(url, opts, t0, "mobile")


def _extract_default(url, t0):
    """Reliable path: yt-dlp's default web/tv clients — their JS challenges go
    through the registered JavaScriptCore provider — plus the account cookies
    when signed in (also unlocks Music-Premium-only tracks)."""
    opts = _base_opts()
    if _cookiefile:
        opts["cookiefile"] = _cookiefile
    return _extract(url, opts, t0, "default" + ("+account" if _cookiefile else ""))


def _arm_latch(reason):
    global _prefer_default_until, _latch_arms
    _latch_arms += 1
    if _latch_arms >= 2:
        # Re-armed after expiring once: enforcement is chronic here — the last
        # expiry let the mobile path mint another 403-poisoned URL within
        # minutes. Hold for the rest of this app session.
        if _prefer_default_until < time.time() + 86400:
            _log("resolve", f"preferring default clients for the rest of this session ({reason})")
        _prefer_default_until = time.time() + 7 * 86400
        return
    if time.time() >= _prefer_default_until:
        _log("resolve", f"preferring default clients for {_LATCH_SECONDS // 60} min ({reason})")
    _prefer_default_until = time.time() + _LATCH_SECONDS


def resolve(url: str) -> str:
    """Resolve a YouTube URL/ID to a JSON track dict (string) with a stream_url."""
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={url}"
    if _known_dead(url):
        return _err_json("This video is not available (removed or blocked).")
    t0 = time.time()
    # While the latch is armed the mobile path is known-bad — reverse the order.
    if time.time() < _prefer_default_until:
        try:
            return _extract_default(url, t0)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            _log("resolve", f"default (latched) failed: {err[:200]}")
            if _is_unavailable(err):
                # No client can resolve a removed/blocked video — don't bother
                # the mobile clients, just remember the verdict.
                _mark_dead(url)
                return _err_json(err)
            try:
                return _extract_mobile(url, t0)
            except Exception as e2:
                err = f"{type(e2).__name__}: {e2}"
                _log("resolve", f"mobile fallback failed: {err[:200]}")
            return _err_json(err)
    try:
        return _extract_mobile(url, t0)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        _log("resolve", f"anonymous failed: {err[:200]}")
        if _is_unavailable(err):
            _mark_dead(url)
            return _err_json(err)
        # The anonymous mobile clients fail in two known ways:
        #  - Music-Premium-only tracks reject them ("premium members");
        #  - YouTube's SABR-only / PO-token experiments strip every direct format
        #    ("Requested format is not available") or bot-wall the session
        #    ("Sign in to confirm").
        # Both recover on the default clients (see _extract_default). A premium
        # wall is per-track, but the experiment failures mean the mobile path is
        # dead for this session — arm the latch so the next resolves skip the
        # doomed 3-8s attempt.
        low = err.lower()
        premium = "premium members" in low
        retriable = (premium
                     or "requested format is not available" in low
                     or "sign in to confirm" in low)
        if retriable:
            _log("resolve", ("premium wall" if premium
                             else "no direct formats from mobile clients")
                            + " — retrying on default clients")
            try:
                out = _extract_default(url, t0)
                if not premium:
                    _arm_latch("mobile clients failing")
                return out
            except Exception as e2:
                err = f"{type(e2).__name__}: {e2}"
                _log("resolve", f"default-client retry failed: {err[:200]}")
                if _is_unavailable(err):
                    _mark_dead(url)
        return _err_json(err)


def resolve_fresh(url: str) -> str:
    """Playback-failure re-resolve (e.g. the CDN 403'd a previously-good URL):
    go straight to the default clients — another anonymous mobile resolve would
    just mint another doomed URL — and arm the latch for the next tracks."""
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={url}"
    if _known_dead(url):
        return _err_json("This video is not available (removed or blocked).")
    _arm_latch("playback failed on a resolved URL")
    t0 = time.time()
    try:
        return _extract_default(url, t0)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        _log("resolve", f"fresh re-resolve failed: {err[:200]}")
        if _is_unavailable(err):
            _mark_dead(url)
        return _err_json(err)


def _diag_resolve(url: str) -> None:
    """Force the `web` client (requires n-sig/signature JS solving) to prove the
    JavaScriptCore provider actually solves challenges inside embedded iOS Python."""
    lines = []

    class L:
        def debug(self, m):
            if any(k in m for k in ("jsc", "JS Challenge", "Solving JS", "JavaScriptCore",
                                    "n challenge", "Signature", "Providers")):
                lines.append(m)
        info = debug
        def warning(self, m):
            lines.append("WARN: " + m)
        def error(self, m):
            lines.append("ERR: " + m)

    opts = {
        "skip_download": True, "format": _M4A_FORMAT, "verbose": True, "logger": L(),
        "extractor_args": {"youtube": {"player_client": ["web"]}},
    }
    got_url = None
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        got_url = info.get("url", "")
    except Exception as e:
        lines.append(f"EXC: {type(e).__name__}: {e}")
    for ln in lines:
        print("JSC_DIAG:", ln[:200], flush=True)
    print("JSC_DIAG: web-client stream host:",
          (got_url.split("/")[2] if got_url and "://" in got_url else got_url),
          flush=True)


def _parse_ytm_duration(t):
    """ytmusicapi gives duration_seconds, or 'duration' as 'M:SS'/'H:MM:SS' — home/search
    items often carry only the text form, so fall back to parsing it (fixes 0:00)."""
    ds = t.get("duration_seconds")
    if ds:
        return int(ds)
    parts = (t.get("duration") or "").split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        pass
    return 0


def _lite(vid, title, uploader, duration, thumbnail=None):
    return {
        "id": vid,
        "title": title or "Unknown",
        "uploader": uploader or "",
        "duration": int(duration or 0),
        "thumbnail": thumbnail or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        "kind": "song",
    }


def _lite_playlist(pid, title, thumbnail=None):
    """A lite row for a playlist/album item (opened, not resolved). `id` is the playlistId
    so the list de-dupes and SwiftUI has a stable identity."""
    return {
        "id": pid,
        "title": title or "Playlist",
        "uploader": "",
        "duration": 0,
        "thumbnail": thumbnail or "",
        "kind": "playlist",
        "playlistId": pid,
    }


def _dedupe(items):
    seen, out = set(), []
    for it in items:
        if it["id"] and it["id"] not in seen:
            seen.add(it["id"])
            out.append(it)
    return out


def _yt_search(query: str, n: int) -> list:
    """YouTube keyword search via yt-dlp ytsearch (flat, fast)."""
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    out = []
    for e in (info.get("entries") or []):
        if e.get("id"):
            out.append(_lite(e["id"], e.get("title"),
                             e.get("uploader") or e.get("channel"), e.get("duration"),
                             e.get("thumbnail")))
    return out


def _ytm_search(query: str, n: int) -> list:
    """YouTube Music search via ytmusicapi (authenticated if signed in)."""
    def go(yt):
        try:
            return yt.search(query, filter="songs", limit=n)
        except Exception:
            return yt.search(query, limit=n)
    res = _ytm_try(go)
    out = []
    for r in res:
        vid = r.get("videoId")
        if not vid:
            continue
        arts = ", ".join(a.get("name", "") for a in (r.get("artists") or []) if a.get("name"))
        thumbs = r.get("thumbnails") or []
        out.append(_lite(vid, r.get("title"), arts, _parse_ytm_duration(r),
                         thumbs[-1].get("url") if thumbs else None))
        if len(out) >= n:
            break
    return out


def search(query: str, source: str = "ytm", n: int = 15) -> str:
    """Keyword search. source: 'yt' | 'ytm' | 'both'. JSON list of lite track dicts."""
    try:
        if source == "yt":
            items = _yt_search(query, n)
        elif source == "both":
            items = _dedupe(_ytm_search(query, n) + _yt_search(query, n))[:n]
        else:  # 'ytm' (default), fall back to YouTube if it yields nothing
            items = _ytm_search(query, n) or _yt_search(query, n)
        _log("search", f"{query!r} via {source} -> {len(items)} items")
        return json.dumps(_dedupe(items))
    except Exception as e:
        _log("search", f"ERROR {type(e).__name__}: {str(e)[:200]}")
        return json.dumps([])


def home(_: str = "") -> str:
    """"For You" feed: the YouTube Music home feed flattened to a JSON list of lite items —
    songs (kind='song', playable) AND playlists/albums (kind='playlist', opened). Mirrors the
    desktop `ytm_home()`/`_parse_home`. Personalizes once signed in."""
    try:
        sections = _ytm_try(lambda yt: yt.get_home(limit=6))
        out = []
        for sec in sections:
            for it in (sec.get("contents") or []):
                if not isinstance(it, dict):
                    continue   # YTM occasionally returns a null entry
                thumbs = it.get("thumbnails") or []
                thumb = thumbs[-1].get("url") if thumbs else None
                if it.get("videoId"):
                    arts = ", ".join(a.get("name", "") for a in (it.get("artists") or [])
                                     if a.get("name"))
                    out.append(_lite(it["videoId"], it.get("title"), arts,
                                     _parse_ytm_duration(it), thumb))
                elif it.get("playlistId"):
                    out.append(_lite_playlist(it["playlistId"], it.get("title"), thumb))
        _log("home", f"feed -> {len(out)} items")
        return json.dumps(_dedupe(out))
    except Exception as e:
        _log("home", f"ERROR {type(e).__name__}: {str(e)[:200]}")
        return json.dumps([])


def _thumb(d):
    thumbs = d.get("thumbnails") or []
    return thumbs[-1].get("url") if thumbs else ""


def durations(ids_csv: str) -> str:
    """Fetch real durations for a comma-separated list of videoIds → JSON {id: seconds}.
    The home feed omits durations, so For You backfills them here. Uses ytmusicapi
    get_song (a light player call, anonymous-ok); one bridge call for the whole batch."""
    from ytmusicapi import YTMusic
    out = {}
    yt = YTMusic()   # get_song is a light anonymous-ok player call; auth adds nothing
    for vid in [v.strip() for v in (ids_csv or "").split(",") if v.strip()]:
        try:
            det = (yt.get_song(vid) or {}).get("videoDetails") or {}
            secs = int(det.get("lengthSeconds") or 0)
            if secs:
                out[vid] = secs
        except Exception:
            continue
    return json.dumps(out)


def search_artist(query: str) -> str:
    """Top artist match for a query → JSON {name, channelId, thumbnail} or {} if none."""
    try:
        res = _ytm_try(lambda yt: yt.search(query, filter="artists", limit=1))
        for r in res:
            cid = r.get("browseId")
            if cid:
                return json.dumps({"name": r.get("artist") or r.get("title") or "",
                                   "channelId": cid, "thumbnail": _thumb(r)})
    except Exception as e:
        _log("artist", f"search ERROR {type(e).__name__}: {str(e)[:200]}")
    return json.dumps({})


def artist(channel_id: str) -> str:
    """Artist page → JSON {name, thumbnail, subscribers, sections:[{title, kind, items:[…]}]}.
    Song/video items are playable lite dicts; album/single items are 'album' lite dicts whose
    id is the album browseId (opened via album())."""
    try:
        a = _ytm_try(lambda yt: yt.get_artist(channel_id))
    except Exception as e:
        _log("artist", f"ERROR {type(e).__name__}: {str(e)[:200]}")
        return json.dumps({})
    sections = []
    for key, title in (("songs", "Songs"), ("albums", "Albums"),
                       ("singles", "Singles"), ("videos", "Videos")):
        block = a.get(key)
        if not isinstance(block, dict):
            continue
        items = []
        for r in (block.get("results") or []):
            if not isinstance(r, dict):
                continue
            if r.get("videoId"):
                arts = ", ".join(x.get("name", "") for x in (r.get("artists") or []) if x.get("name"))
                items.append(_lite(r["videoId"], r.get("title"),
                                   arts or a.get("name", ""), _parse_ytm_duration(r), _thumb(r)))
            elif r.get("browseId"):   # album / single → opened via album()
                it = _lite_playlist(r["browseId"], r.get("title"), _thumb(r))
                it["kind"] = "album"
                items.append(it)
        if items:
            sections.append({"title": title, "kind": key, "items": items})
    return json.dumps({
        "name": a.get("name") or "",
        "thumbnail": _thumb(a),
        "subscribers": a.get("subscribers") or "",
        "sections": sections,
    })


def album(browse_id: str) -> str:
    """Album tracks (via get_album) → JSON list of lite song dicts."""
    try:
        data = _ytm_try(lambda yt: yt.get_album(browse_id))
        out = []
        for t in (data.get("tracks") or []):
            vid = t.get("videoId")
            if not vid:
                continue
            arts = ", ".join(x.get("name", "") for x in (t.get("artists") or []) if x.get("name"))
            out.append(_lite(vid, t.get("title"), arts, _parse_ytm_duration(t), _thumb(t)))
        return json.dumps(_dedupe(out))
    except Exception as e:
        _log("album", f"ERROR {type(e).__name__}: {str(e)[:200]}")
        return json.dumps([])


def radio(video_id: str) -> str:
    """Endless mix seeded from a track (get_watch_playlist radio) → JSON list of lite dicts."""
    try:
        data = _ytm_try(lambda yt: yt.get_watch_playlist(videoId=video_id, radio=True, limit=25))
    except Exception as e:
        _log("radio", f"ERROR {type(e).__name__}: {str(e)[:200]}")
        return json.dumps([])
    out = []
    for t in (data.get("tracks") or []):
        vid = t.get("videoId")
        if not vid:
            continue
        arts = ", ".join(x.get("name", "") for x in (t.get("artists") or []) if x.get("name"))
        dur = _parse_ytm_duration(t)
        if not dur and t.get("length"):   # watch-playlist tracks carry 'length' (M:SS)
            dur = _parse_ytm_duration({"duration": t.get("length")})
        out.append(_lite(vid, t.get("title"), arts, dur, _thumb(t)))
    return json.dumps(_dedupe(out))


def lyrics(video_id: str) -> str:
    """Lyrics for a videoId → JSON {ok, synced, lines:[{text,start,end}], text, source}.
    Requests timestamps so the player can follow along; falls back to plain when a song has
    no timing. start/end are milliseconds (0 when not synced). ok=False when unavailable."""
    # Use an ANONYMOUS client: get_lyrics(timestamps=True) runs inside as_mobile()
    # (ANDROID_MUSIC context), which rejects cookie/browser auth with HTTP 400 — so once
    # signed in, every timestamped lyrics call fails. Lyrics are public, so a signed-out
    # client works for everyone. Fall back to plain if the timestamped call can't be fetched.
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        wp = yt.get_watch_playlist(videoId=video_id, limit=1)
        bid = wp.get("lyrics")
        if not bid:
            return json.dumps({"ok": False})
        try:
            lyr = yt.get_lyrics(bid, timestamps=True)
        except Exception:
            lyr = yt.get_lyrics(bid, timestamps=False)
    except Exception as e:
        _log("lyrics", f"ERROR {type(e).__name__}: {str(e)[:200]}")
        return json.dumps({"ok": False})
    if not lyr:
        return json.dumps({"ok": False})

    def _g(obj, k):
        return obj.get(k) if isinstance(obj, dict) else getattr(obj, k, None)

    source = _g(lyr, "source") or ""
    if _g(lyr, "hasTimestamps"):
        lines = [{"text": _g(ln, "text") or "",
                  "start": int(_g(ln, "start_time") or 0),
                  "end": int(_g(ln, "end_time") or 0)} for ln in (_g(lyr, "lyrics") or [])]
        if lines:
            return json.dumps({"ok": True, "synced": True, "lines": lines,
                               "text": "\n".join(l["text"] for l in lines), "source": source})
    text = _g(lyr, "lyrics")
    if not isinstance(text, str) or not text:
        return json.dumps({"ok": False})
    lines = [{"text": t, "start": 0, "end": 0} for t in text.split("\n")]
    return json.dumps({"ok": True, "synced": False, "lines": lines,
                       "text": text, "source": source})


def translate(text: str, target: str = "en") -> str:
    """Translate a whole text block to `target` in ONE request (free Google endpoint).
    Newlines preserved → the caller splits back into per-line translations. Returns
    JSON {ok, text}."""
    if not text:
        return json.dumps({"ok": False, "text": ""})
    try:
        import requests
        params = {"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text}
        r = requests.get("https://translate.googleapis.com/translate_a/single",
                         params=params, timeout=20)
        data = r.json()
        out = "".join(seg[0] for seg in data[0] if seg and seg[0])
        return json.dumps({"ok": bool(out), "text": out})
    except Exception as e:
        _log("translate", f"ERROR {type(e).__name__}: {str(e)[:200]}")
        return json.dumps({"ok": False, "text": ""})


def _ytm_playlist(playlist_id: str) -> list:
    """Full playlist via ytmusicapi (paginates all tracks — no 100-ish cap)."""
    pid = playlist_id[2:] if playlist_id.startswith("VL") else playlist_id
    data = _ytm_try(lambda yt: yt.get_playlist(pid, limit=None))
    out = []
    for t in (data.get("tracks") or []):
        vid = t.get("videoId")
        if not vid:
            continue
        arts = ", ".join(a.get("name", "") for a in (t.get("artists") or []) if a.get("name"))
        thumbs = t.get("thumbnails") or []
        out.append(_lite(vid, t.get("title"), arts, _parse_ytm_duration(t),
                         thumbs[-1].get("url") if thumbs else None))
    return out


def browse(url: str) -> str:
    """Resolve a YouTube/YT-Music URL (playlist or single video) → JSON list of lite dicts
    (flat). YT-Music playlists use ytmusicapi (full pagination); else yt-dlp flat."""
    import urllib.parse
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    list_id = (params.get("list") or [None])[0]

    # Playlist URL → try ytmusicapi first (handles 1000+ tracks), fall back to yt-dlp.
    if list_id:
        try:
            items = _ytm_playlist(list_id)
            if items:
                return json.dumps(_dedupe(items))
        except Exception as e:
            _log("browse", f"ytm playlist failed ({type(e).__name__}: {str(e)[:120]}) — trying yt-dlp")

    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": "in_playlist"}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        entries = info.get("entries")
        if entries is None:  # single video
            entries = [info]
        out = []
        for e in entries:
            if e and e.get("id"):
                out.append(_lite(e["id"], e.get("title"),
                                 e.get("uploader") or e.get("channel") or e.get("artist"),
                                 e.get("duration"), e.get("thumbnail")))
        return json.dumps(_dedupe(out))
    except Exception as e:
        _log("browse", f"ERROR {type(e).__name__}: {str(e)[:200]}")
        return json.dumps([])


def selftest() -> str:
    """Run a default resolution + a forced-web-client JSC probe; print + return JSON.
    `_probe_jsc` proves the JavaScriptCore challenge solver runs on-device."""
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    out = resolve(url)
    print("RESOLVE_RESULT:", out, flush=True)
    print("JSC_PROBE:", json.dumps(_probe_jsc(url)), flush=True)
    return out


if __name__ == "__main__":
    print(selftest())
