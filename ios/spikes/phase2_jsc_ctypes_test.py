#!/usr/bin/env python3
"""Validate the pure-Python ctypes->JavaScriptCore provider (ios_jsc_provider.py).

Same JavaScriptCore C API as iOS, so a PASS here is the real on-device code path.
Run with deno/node hidden so JavaScriptCore is provably the solver:

    env PATH="/usr/bin:/bin" python ios/spikes/phase2_jsc_ctypes_test.py [url]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "YTMusic"))
import ios_jsc_provider  # noqa: F401  (registers JavaScriptCoreJCP)
import yt_dlp


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    warns = []

    class L:
        def debug(self, m): pass
        def info(self, m): pass
        def warning(self, m): warns.append(m)
        def error(self, m): warns.append(m)

    opts = {
        "quiet": True, "skip_download": True,
        "format": "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio",
        "logger": L(),
    }
    print("Resolving:", url)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    u = info.get("url", "")
    fail = any("olving failed" in m for m in warns)
    print("title :", info.get("title"))
    print("ext   :", info.get("ext"), "| acodec:", info.get("acodec"),
          "| abr:", info.get("abr"))
    print("host  :", u.split("/")[2] if "://" in u else u[:60])
    for m in warns:
        print("  [warn]", m[:160])
    ok = (info.get("ext") == "m4a" and str(info.get("acodec", "")).startswith("mp4a")
          and "googlevideo" in u and not fail)
    print("RESULT:", "PASS ✅" if ok else "FAIL ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
