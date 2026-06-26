"""App-side YouTube resolver for the embedded-Python iOS spike.

Mirrors the desktop `youtube._entry_to_dict` track shape and forces an m4a/AAC
format for AVPlayer. JS challenges are solved on-device by the JavaScriptCore
provider (`ios_jsc_provider`), registered on import.
"""
from __future__ import annotations

import json
import os
import sys
import time

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


def resolve(url: str) -> str:
    """Resolve a YouTube URL/ID to a JSON track dict (string) with a stream_url."""
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={url}"
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "format": _M4A_FORMAT,
    }
    t0 = time.time()
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        d = _entry_to_dict(info)
        d["_elapsed_s"] = round(time.time() - t0, 2)
        d["_ok"] = bool(d["stream_url"] and "googlevideo" in d["stream_url"])
        return json.dumps(d)
    except Exception as e:
        return json.dumps({"_ok": False, "_error": f"{type(e).__name__}: {e}"})


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
