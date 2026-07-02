# YT Music — native iOS

Native iOS app (SwiftUI + embedded Python `yt-dlp`) — the full port described in
`../NATIVE_REWRITE.md`. Streams YouTube Music to AVPlayer on-device: search, queue,
library, For You feed, account sign-in, themes + color-wave, timed lyrics with
translation, radio (endless mix), lock-screen controls and an equalizer visualizer.
Runs on iPhone and iPad (iOS 16+).

## What's here

| Path | Role |
|------|------|
| `project.yml` | XcodeGen spec → `YTMusic.xcodeproj` (generated, git-ignored) |
| `YTMusic/` | SwiftUI app + `PythonBootstrap.m` (isolated `PyConfig` init + `python_*` bridge) |
| `app/resolve.py` | All Python entry points: resolve, search, home, artist, album/playlist, lyrics, translate, radio (JSON in/out) |
| `app/ios_jsc_provider.py` | **Pure-Python** yt-dlp JS-challenge provider via `ctypes`→JavaScriptCore C API (no Swift bridge) |
| `app_packages/` | Vendored pure-Python `yt-dlp` + `ytmusicapi` + deps (git-ignored) |
| `Support/Python.xcframework` | python-apple-support 3.13 (git-ignored, ~146MB) |
| `Support/VERSIONS` | Pinned versions of the vendored deps |
| `build.sh` / `fetch-deps.sh` | Build/run + dependency reproduction |

## Build & run

```sh
brew install xcodegen          # one-time
./fetch-deps.sh                # downloads Python.xcframework + vendors deps
./build.sh sim                 # build → install → launch on iOS Simulator
./build.sh device <TEAMID> [device-id]   # build for a connected iPhone/iPad
```

After a device build, install + launch with:

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
xcrun devicectl device install app --device <id> build/Build/Products/Debug-iphoneos/YTMusic.app
xcrun devicectl device process launch --console --device <id> com.ytmtui.YTMusic
```

One-time per device: enable Developer Mode (Settings → Privacy & Security) and trust the
dev profile (Settings → General → VPN & Device Management).

## How it works (key design)

- **Embedding:** `PythonBootstrap.m` mirrors python-apple-support's testbed: isolated
  `PyConfig`, `PYTHONHOME=<bundle>/python`, `app_packages` via `site.addsitedir`,
  `write_bytecode=0`. A post-build phase (`install_python` from the xcframework) stages the
  stdlib and repackages each stdlib `.so` as a signed framework (iOS requirement).
- **JS challenges:** yt-dlp needs a JS runtime to solve YouTube's `n`/signature
  challenges; iOS bans JIT (no Deno/Node). `ios_jsc_provider.py` registers a custom
  `JsChallengeProvider` that runs the EJS solver via **JavaScriptCore's C API through
  ctypes** — pure Python, identical on host and device.
- In practice the default `android_vr` client often returns a playable m4a without any JS
  solving (~4s); JavaScriptCore is the on-device fallback when YouTube forces a challenge.

## Gotchas

- **Single-arch only:** `install_python`'s `lib-$ARCHS` breaks on multi-arch
  (`arm64 x86_64`). Build with `ARCHS=arm64 ONLY_ACTIVE_ARCH=YES` (baked into `build.sh`).
- **Embedded Python stdout isn't captured** — surface results via NSLog / the returned
  JSON, not `print()`.
- The simulator runtime is an ~8.5GB download (`xcodebuild -downloadPlatform iOS`) and is
  also required for device builds.
- More in the repo-root `CLAUDE.md`.
