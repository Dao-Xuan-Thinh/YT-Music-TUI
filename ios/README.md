# YT Music — native iOS (extraction spike)

Native iOS app (SwiftUI + embedded Python `yt-dlp`) for the rewrite described in
`../NATIVE_REWRITE.md`. **Milestone 1 status: PASSED on the iOS Simulator** — embedded
CPython runs `yt-dlp` in-app and resolves YouTube to an AVPlayer-ready `m4a` URL, with
on-device JS-challenge solving via JavaScriptCore. Remaining: run on a physical device
(Phase 3, needs an Apple ID).

## What's here

| Path | Role |
|------|------|
| `project.yml` | XcodeGen spec → `YTMusic.xcodeproj` (generated, git-ignored) |
| `YTMusic/` | Swift app + `PythonBootstrap.m` (isolated `PyConfig` init + `python_resolve`) |
| `app/resolve.py` | Resolver: m4a format + JSON track dict (desktop-compatible shape) |
| `app/ios_jsc_provider.py` | **Pure-Python** yt-dlp JS-challenge provider via `ctypes`→JavaScriptCore C API (no Swift bridge) |
| `app_packages/` | Vendored pure-Python `yt-dlp` + `yt-dlp-ejs` + `certifi` (git-ignored) |
| `Support/Python.xcframework` | python-apple-support 3.13 (git-ignored, ~146MB) |
| `spikes/` | Host-side proofs (`phase0`/`phase2`) for the JS-solving approach |
| `build.sh` / `fetch-deps.sh` | Build/run + dependency reproduction |

## Build & run

```sh
brew install xcodegen          # one-time
./fetch-deps.sh                # downloads Python.xcframework + vendors deps
./build.sh sim                 # build → install → launch on iOS Simulator
```
The app auto-resolves a test track on launch and logs `RESOLVE_RESULT: {...}` (via NSLog).
Expect `"_ok": true, "ext": "m4a", "acodec": "mp4a.40.2"`.

## How it works (key design)

- **Embedding:** `PythonBootstrap.m` mirrors python-apple-support's testbed: isolated
  `PyConfig`, `PYTHONHOME=<bundle>/python`, `app_packages` via `site.addsitedir`,
  `write_bytecode=0`. A post-build phase (`install_python` from the xcframework) stages the
  stdlib and repackages each stdlib `.so` as a signed framework (iOS requirement).
- **JS challenges:** yt-dlp 2026 needs a JS runtime to solve YouTube's `n`/signature
  challenges; iOS bans JIT (no Deno/Node). `ios_jsc_provider.py` registers a custom
  `JsChallengeProvider` that runs the EJS solver via **JavaScriptCore's C API through
  ctypes** — pure Python, identical on host and device. Confirmed in-app:
  `[jsc:JavaScriptCore] Solving JS challenges using JavaScriptCore`.
- In practice the default `android_vr` client often returns a playable m4a without any JS
  solving (~4s); JavaScriptCore is the on-device fallback when YouTube forces a challenge.

## Phase 3 — run on a real device (needs your Apple ID)

1. Connect an iPhone via USB; trust the Mac.
2. Xcode → Settings → Accounts → add your Apple ID (free works for 7-day signing).
3. Find your team id: `xcrun security find-identity -v -p codesigning` or Xcode signing UI.
4. `./build.sh device <TEAMID>` then install with `xcrun devicectl device install app …`
   (the script prints the exact command).
5. Verify the same `RESOLVE_RESULT` on-device, then proceed to Milestone 2 (AVPlayer +
   background/lock-screen audio).

## Gotchas hit during the spike

- **Single-arch only:** `install_python`'s `lib-$ARCHS` breaks on multi-arch (`arm64 x86_64`).
  Build with `ARCHS=arm64 ONLY_ACTIVE_ARCH=YES` (baked into `build.sh`).
- **Embedded Python stdout isn't captured** by `simctl` — surface results via NSLog / the
  returned JSON, not `print()`.
- The simulator runtime is an ~8.5GB download (`xcodebuild -downloadPlatform iOS`).
