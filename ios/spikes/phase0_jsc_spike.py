#!/usr/bin/env python3
"""Phase 0 go/no-go: prove YouTube's JS challenges solve under Apple JavaScriptCore (jsc).

Registers a custom yt-dlp JsChallengeProvider whose _run_js_runtime evaluates the
EJS solver program in Apple's `jsc` CLI (same engine as iOS JSContext), then resolves
a real video and asserts an unthrottled m4a URL with signature + n-sig solved.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import warnings

JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"

# jsc exposes `print`, not `console`. The EJS program's only output is its final
# console.log(JSON.stringify(...)); shim console.* -> print so that line reaches stdout.
CONSOLE_SHIM = (
    "globalThis.console = globalThis.console || "
    "{log:print, debug:function(){}, info:print, warn:function(){}, error:print};\n"
)

from yt_dlp.extractor.youtube.jsc._builtin.ejs import EJSBaseJCP
from yt_dlp.extractor.youtube.jsc.provider import (
    register_preference, register_provider,
)
from yt_dlp.extractor.youtube.pot._provider import BuiltinIEContentProvider


@register_provider
class JavaScriptCoreJCP(EJSBaseJCP, BuiltinIEContentProvider):
    PROVIDER_NAME = "JavaScriptCore"
    JS_RUNTIME_NAME = "JavaScriptCore"

    # We run jsc from a fixed framework path (iOS will use JSContext), so we are
    # available without a PATH-detected runtime binary. Don't gate on runtime_info.
    def is_available(self, /) -> bool:
        return self._available

    def _run_js_runtime(self, stdin: str, /) -> str:
        program = CONSOLE_SHIM + stdin
        tf = tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False, encoding="utf-8")
        try:
            tf.write(program)
            tf.close()
            proc = subprocess.run(
                [JSC, tf.name], capture_output=True, text=True, timeout=120,
            )
            if proc.returncode:
                raise RuntimeError(f"jsc rc={proc.returncode}: {proc.stderr.strip()[:500]}")
            out = proc.stdout.strip()
            # The result is the last non-empty line (defensive against stray prints).
            last = [ln for ln in out.splitlines() if ln.strip()][-1]
            return last
        finally:
            pathlib.Path(tf.name).unlink(missing_ok=True)


@register_preference(JavaScriptCoreJCP)
def _pref(*_):
    return 100000  # outrank deno/quickjs/etc so our provider is chosen


def main():
    import yt_dlp

    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    captured = []

    class CaptureLogger:
        def debug(self, m): pass
        def info(self, m): pass
        def warning(self, m): captured.append(("WARN", m))
        def error(self, m): captured.append(("ERR", m))

    opts = {
        "quiet": True, "no_warnings": False, "skip_download": True,
        "format": "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio",
        "logger": CaptureLogger(),
    }
    print(f"Resolving: {url}")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    sig_fail = any("ignature solving failed" in m or "n challenge solving failed" in m
                   for _, m in captured)
    print("\n--- RESULT ---")
    print("title :", info.get("title"))
    print("ext   :", info.get("ext"), "| acodec:", info.get("acodec"),
          "| abr:", info.get("abr"), "| proto:", info.get("protocol"))
    u = info.get("url", "")
    print("host  :", u.split("/")[2] if "://" in u else u[:60])
    print("\ncaptured warnings:")
    for lvl, m in captured:
        print(f"  [{lvl}] {m[:160]}")
    ok = (info.get("ext") == "m4a" and str(info.get("acodec", "")).startswith("mp4a")
          and "googlevideo" in u and not sig_fail)
    print("\nGO/NO-GO:", "PASS ✅" if ok else "FAIL ❌",
          "(m4a+mp4a+googlevideo, no JS-solve failures)" if ok else "")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
