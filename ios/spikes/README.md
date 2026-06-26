# iOS spikes

Throwaway proofs-of-concept for the native rewrite (`NATIVE_REWRITE.md`).

## `phase0_jsc_spike.py` — Milestone 1 go/no-go (PASSED ✅)

Proves YouTube's signature + `n` JS challenges can be solved by **Apple
JavaScriptCore** (the same engine as iOS `JSContext`), so the embedded-Python
extraction path is viable on-device with no Deno/Node/server.

**How it works:** registers a custom `yt-dlp` `JsChallengeProvider`
(`JavaScriptCoreJCP`, subclass of `EJSBaseJCP`) whose `_run_js_runtime` writes the
EJS solver program to a temp `.js` and evaluates it with Apple's `jsc` CLI
(`/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc`).
`EJSBaseJCP._construct_stdin` builds a *complete self-contained program*
(`lib.min.js` + `core.min.js` + `console.log(JSON.stringify(jsc(data)))`), so the
runtime only needs to eval JS and capture `console.log` — exactly what
`JSContext.evaluateScript` does. A 1-line `console`→`print` shim is prepended.

**Run it (must hide deno/node so jsc is the only available provider):**
```sh
pip install yt-dlp-ejs            # ships the runtime-agnostic lib.min.js/core.min.js
env PATH="/usr/bin:/bin" python ios/spikes/phase0_jsc_spike.py [youtube_url]
```
Expect `[jsc:JavaScriptCore] Solving JS challenges using JavaScriptCore` and a
`m4a / mp4a.40.2 / googlevideo` result with no JS-solve warnings.

**Gotcha that bit us:** `deno` was installed via homebrew, so early runs silently
solved with deno while our provider showed `(unavailable)`. Hide deno/node from
PATH to actually exercise jsc. Availability also requires overriding
`is_available()` (the base gates on a PATH-detected `runtime_info`, which a
fixed-path jsc provider has none of).

**Phase 2 port:** this `_run_js_runtime` becomes `_iosbridge.run_js(program)`,
where the Swift side evaluates `program` in a long-lived `JSContext`.
