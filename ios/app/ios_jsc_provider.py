"""On-device YouTube JS-challenge provider backed by JavaScriptCore (pure Python).

yt-dlp 2026+ needs a JS runtime to solve YouTube's `signature` + `n` challenges.
iOS bans JIT, so Deno/Node/Bun/QuickJS can't run. JavaScriptCore (`JSContext`) is the
only sanctioned engine — and it exposes a **C API** we reach via `ctypes`, so this whole
provider is pure Python with no Swift bridge. The same framework exists on macOS, so this
file runs identically on the host (for testing) and on iOS/ipados.

yt-dlp's `EJSBaseJCP` builds a self-contained JS program (`lib.min.js` + `core.min.js` +
`console.log(JSON.stringify(jsc(data)))`). We eval that program in a long-lived JSContext
with a `console.log` shim that captures the single JSON line, then hand it back.

Usage: `import ios_jsc_provider` (registers the provider) before resolving with yt-dlp.
Requires `yt-dlp-ejs` (ships the solver scripts).
"""
from __future__ import annotations

import ctypes
import ctypes.util

# --- JavaScriptCore C API via ctypes -----------------------------------------

_CANDIDATE_PATHS = [
    "/System/Library/Frameworks/JavaScriptCore.framework/JavaScriptCore",
    "JavaScriptCore.framework/JavaScriptCore",
    "JavaScriptCore",
]


def _load_jsc() -> ctypes.CDLL:
    last = None
    for name in _CANDIDATE_PATHS:
        try:
            return ctypes.CDLL(name)
        except OSError as e:  # pragma: no cover - platform dependent
            last = e
    found = ctypes.util.find_library("JavaScriptCore")
    if found:
        return ctypes.CDLL(found)
    raise OSError(f"Could not load JavaScriptCore framework: {last}")


class _JSCore:
    """Thin ctypes wrapper around the JavaScriptCore C API (one persistent context)."""

    def __init__(self):
        jsc = _load_jsc()
        cvp, cint, csize, cchar = (
            ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_char_p,
        )
        P = ctypes.POINTER(cvp)

        def sig(fn, restype, argtypes):
            fn.restype = restype
            fn.argtypes = argtypes
            return fn

        self._str_new = sig(jsc.JSStringCreateWithUTF8CString, cvp, [cchar])
        self._str_release = sig(jsc.JSStringRelease, None, [cvp])
        self._str_maxsize = sig(jsc.JSStringGetMaximumUTF8CStringSize, csize, [cvp])
        self._str_getutf8 = sig(jsc.JSStringGetUTF8CString, csize, [cvp, cchar, csize])
        self._ctx_create = sig(jsc.JSGlobalContextCreate, cvp, [cvp])
        self._eval = sig(
            jsc.JSEvaluateScript, cvp, [cvp, cvp, cvp, cvp, cint, P])
        self._to_string = sig(jsc.JSValueToStringCopy, cvp, [cvp, cvp, P])

        self._ctx = self._ctx_create(None)
        if not self._ctx:
            raise RuntimeError("JSGlobalContextCreate returned NULL")

    def _eval_raw(self, source: str) -> ctypes.c_void_p:
        s = self._str_new(source.encode("utf-8"))
        exc = ctypes.c_void_p(0)
        try:
            val = self._eval(self._ctx, s, None, None, 0, ctypes.byref(exc))
        finally:
            self._str_release(s)
        if exc.value:
            raise RuntimeError(f"JS exception: {self._jsval_to_str(exc)!r}")
        return val

    def _jsval_to_str(self, val) -> str:
        if not val:
            return ""
        exc = ctypes.c_void_p(0)
        js_str = self._to_string(self._ctx, val, ctypes.byref(exc))
        if not js_str:
            return ""
        try:
            n = self._str_maxsize(js_str)
            buf = ctypes.create_string_buffer(n)
            self._str_getutf8(js_str, buf, n)
            return buf.value.decode("utf-8")
        finally:
            self._str_release(js_str)

    def run_program(self, program: str) -> str:
        """Eval an EJS solver program; return what its console.log emitted (JSON)."""
        shim = (
            "globalThis.__out__ = '';"
            "globalThis.console = {log:function(s){globalThis.__out__ = String(s);},"
            "debug:function(){},info:function(){},warn:function(){},error:function(){}};"
        )
        self._eval_raw(shim)
        self._eval_raw(program)
        return self._jsval_to_str(self._eval_raw("globalThis.__out__"))


_JSC_SINGLETON: _JSCore | None = None


def _jsc() -> _JSCore:
    global _JSC_SINGLETON
    if _JSC_SINGLETON is None:
        _JSC_SINGLETON = _JSCore()
    return _JSC_SINGLETON


# --- yt-dlp provider ----------------------------------------------------------

from yt_dlp.extractor.youtube.jsc._builtin.ejs import EJSBaseJCP
from yt_dlp.extractor.youtube.jsc.provider import register_preference, register_provider
from yt_dlp.extractor.youtube.pot._provider import BuiltinIEContentProvider


@register_provider
class JavaScriptCoreJCP(EJSBaseJCP, BuiltinIEContentProvider):
    PROVIDER_NAME = "JavaScriptCore"
    JS_RUNTIME_NAME = "JavaScriptCore"

    # Fixed-path system framework, not a PATH-detected runtime binary: always available.
    def is_available(self, /) -> bool:
        return self._available

    def _run_js_runtime(self, stdin: str, /) -> str:
        return _jsc().run_program(stdin)


@register_preference(JavaScriptCoreJCP)
def _prefer_jsc(*_):
    # Outrank the (unavailable on iOS) subprocess providers.
    return 100000
