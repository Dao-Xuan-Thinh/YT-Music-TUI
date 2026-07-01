# Native iOS rewrite — design & plan (`mobile-fork`)

> **Status:** design kickoff. This branch holds the native (Apple) rewrite. The
> existing Python/Textual app stays the cross-platform desktop version on
> `master`/`test`. This document is written from a Windows host that **cannot
> build iOS** — compilation/verification happens on the Mac mini. Treat code here
> as a blueprint to build *there*, then iterate from real Xcode output.

## ▶ Resuming on the Mac mini (start here)

The Claude Code session from the Windows box does **not** sync — but the work does
(it's all in git + these docs). To pick up:

1. `git clone git@github.com:Dao-Xuan-Thinh/YT-Music-TUI.git && cd YT-Music-TUI`
2. `git checkout mobile-fork`
3. Start Claude Code in the folder and say: *"Read `NATIVE_REWRITE.md` and
   `CLAUDE.md`; we're doing the SwiftUI + AVPlayer + embedded-Python native
   rewrite — start with Milestone 1 (extraction spike)."*

**State as of this kickoff:**
- Desktop app is feature-complete on `master`/`test` (library management, themes,
  color-wave, auth, the Termux socket-path fix). No native code exists yet.
- **Decision locked:** SwiftUI + AVPlayer (force m4a/AAC) + embedded Python
  (`python-apple-support`) running `yt-dlp` for extraction. MPVKit = optional
  Phase 2 (Opus / desktop parity).
- **First task = Milestone 1**, the go/no-go gate: prove `yt-dlp` runs embedded on
  a real device and resolves a video to a playable `m4a` URL. Everything else is
  low-risk once that works.

## Goal

A native iOS/iPadOS app that runs **on the device** with **audio out the device**,
including **background + lock-screen playback** — the one thing the desktop TUI
(and a UTM VM) can't do well on iOS.

## Chosen stack (decision recorded)

**SwiftUI + AVPlayer + embedded Python (`yt-dlp`) for extraction.**

- **UI:** SwiftUI (native, best touch UX, lock-screen/Control-Center integration).
- **Audio:** `AVPlayer` + `AVAudioSession` (`.playback` category) for background
  audio; `MPNowPlayingInfoCenter` + `MPRemoteCommandCenter` for lock-screen and
  AirPods/Control-Center transport. *Phase 2:* swap to **MPVKit** (embeds mpv) if
  Opus/WebM playback or exact desktop parity is wanted (AVPlayer can't decode Opus).
- **Extraction:** **embed CPython on iOS** via Apple's `python-apple-support`
  (`Python.xcframework`) and run **`yt-dlp`** as a module. Swift-only extractors
  (XCDYouTubeKit/YouTubeKit) are rejected — they break whenever YouTube changes;
  yt-dlp is the maintained source of truth.

### Why not the alternatives
- *BeeWare/Briefcase:* max Python reuse, but Toga-iOS is thinner and background
  audio via rubicon-objc is fiddlier than doing it natively.
- *Pythonista/Pyto + AVPlayer:* fastest hack, but not a standalone `.ipa` (depends
  on a paid host app) and the Textual UI doesn't port.

## The audio nuance (must-handle)

YouTube's best audio is often **Opus/WebM → AVPlayer can't play it**. So in the
extraction step, **constrain `yt-dlp` to an `m4a`/AAC progressive or HLS format**
(e.g. format selector `bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]`). Hand the
resulting direct URL to `AVPlayer`. (MPVKit removes this constraint in Phase 2.)

## Reuse map — desktop module → native counterpart

| Desktop (`master`) | Native plan |
|---|---|
| `youtube.py` (yt-dlp/ytmusicapi wrapper) | **Reused via embedded Python** — call `yt-dlp`/`ytmusicapi` from a thin Swift↔Python bridge; keep the resolve/search/`ytm_home` logic. |
| `library.py` (liked/playlists/folders/recent/sessions JSON) | Reimplement in Swift as a small `Codable` store (same JSON shape), **or** reuse the Python module via the bridge. It's ~200 lines of pure logic. |
| `config.py` (settings JSON) | Swift `Codable` (`UserDefaults` or a JSON file). |
| `player.py` (mpv IPC) | **Replaced** by `AVPlayer` (Phase 1) / MPVKit (Phase 2) + `AVAudioSession`. |
| `main.py` (Textual UI) | **Replaced** by SwiftUI views (search, results list, now-playing, library tabs, settings). |
| `offline.py` | Optional later (local file playback via AVAudioPlayer + document picker). |
| `updater.py` | N/A (App-store/sideload update flow instead). |

## Track data model (keep identical to desktop)

```swift
struct Track: Codable, Identifiable {
    let id: String          // videoId (or file path offline)
    let title: String
    let uploader: String
    let duration: Int
    let url: String         // https://www.youtube.com/watch?v=<id>
    let thumbnail: String
}
```
Same `{id,title,uploader,duration,url,thumbnail}` shape as `youtube._ytm_track_to_dict`,
so library JSON stays portable between desktop and mobile.

## Architecture sketch

```
SwiftUI Views ─► ViewModels (ObservableObject)
                     │
     ┌───────────────┼────────────────────────┐
     ▼               ▼                         ▼
 PlaybackService   ExtractionBridge        LibraryStore
 (AVPlayer +       (embedded Python:        (Codable JSON,
  AVAudioSession +  yt-dlp resolve/search/   liked/playlists/
  NowPlayingInfo)   ytm_home)                recent/sessions)
```

## Milestone 1 result — go/no-go PASSED ✅ (host-validated)

The riskiest unknown is now de-risked on the Mac (see `ios/spikes/phase0_jsc_spike.py`).
Two findings reshaped the spike:

- **yt-dlp 2026.06 needs a JS runtime** to solve YouTube's `signature` + `n`
  challenges (Deno/Node/Bun/QuickJS/EJS). With none installed, solving *fails* and
  formats are missing/throttled. iOS bans JIT → none of those binaries can run
  on-device.
- **JavaScriptCore solves them.** yt-dlp exposes a pluggable JSC provider system
  (`register_provider`). The EJS base (`EJSBaseJCP`) builds a *self-contained* JS
  program (`lib.min.js`+`core.min.js`+`console.log(JSON.stringify(jsc(data)))`) and
  hands it to `_run_js_runtime(program)`. We subclassed it to eval that program in
  Apple's `jsc` (the same engine as iOS `JSContext`). Verified jsc-only (deno/node
  hidden from PATH) across 3 videos → `[jsc:JavaScriptCore] Solving JS challenges` →
  clean `m4a / mp4a.40.2 / googlevideo` URL, no solve warnings, ~3.2s end-to-end.

**On iOS the entire port is one method:** `_run_js_runtime(program)` →
`_iosbridge.run_js(program)` where Swift evals `program` in a long-lived `JSContext`
with a `console.log` shim. No Deno, no server, no throttling.

## Milestone 1 — now PROVEN in-app on the iOS Simulator ✅

The full extraction chain runs inside a real SwiftUI app on the iOS 26.5 Simulator
runtime (see `ios/`, built via XcodeGen + python-apple-support 3.13):

- **Embedded CPython boots in-app** and imports `yt-dlp` (`PythonBootstrap.m`, isolated
  `PyConfig` mirroring the support package's testbed).
- **JavaScriptCore solves challenges on-device, in embedded Python.** The JSC provider is
  now **pure Python via `ctypes` → JavaScriptCore C API** (`ios/app/ios_jsc_provider.py`)
  — no Swift bridge. Confirmed in the running app:
  `[jsc:JavaScriptCore] Solving JS challenges using JavaScriptCore` (only provider
  available; deno/node/bun/quickjs all unavailable on iOS).
- **Resolves to AVPlayer-ready m4a:** `_ok=true, ext=m4a, acodec=mp4a.40.2`, direct
  `googlevideo` URL, ~4s. In practice the default `android_vr` client returns a playable
  m4a *without* needing JS solving; JavaScriptCore is the proven fallback.

Run it: `cd ios && ./fetch-deps.sh && ./build.sh sim`. Remaining gate: a physical device.

## Milestones

1. **Spike — extraction.** ✅ Host-validated, in-app on Simulator, and on a physical device.
2. **Playback.** ✅ `AVPlayer` plays that URL; `AVAudioSession` background mode;
   lock-screen controls via `MPNowPlayingInfoCenter`/`MPRemoteCommandCenter`.
3. **Search + results UI.** ✅ SwiftUI search → bridge `search()` → results list →
   tap to play; queue + auto-advance (+ M3.5/M3.6 fix rounds).
4. **Library.** ✅ Liked / playlists / recent / sessions, reimplemented in Swift as
   `LibraryStore` (Codable JSON in Documents, mirroring desktop `library.py`'s
   `liked`/`playlists`/`recent`/`sessions` shapes). UI is a third **LIBRARY** tab with
   `liked / playlists / recent / resume` sub-sections; ♥ toggle in the now-playing bar,
   `+pl` saves the queue as a named playlist, sessions auto-save on backgrounding and
   restore queue+position. Builds + runs on device.
5. **Polish.** ✅ Full-screen Now-Playing (artwork/scrubber/transport, swipe-dismiss);
   6 themes + animated color-wave (`ThemeManager` + `WaveText`); Settings sheet (theme
   picker, default source/volume, clear-library, about); For You feed (`resolve.home()`
   anonymous, personalizes when signed in); account sign-in — in-app WKWebView login
   (desktop UA) + paste-cookies fallback → ytmusicapi browser auth (`set_auth`),
   persisted/re-armed at launch. Plus M5-A fixes (search-clear, playlist view-not-play,
   app icon).
6. **Polish round 2 (device feedback).** ✅ `WaveText` rewritten as an animated gradient
   (fixes long-title overlap) + applied to the playing list row; **15 themes** ported from
   desktop (`AppTheme.make`/`Color(hex:)`, light+dark) with a footer **theme-picker popup**;
   footer drops the source chip + gains the gear, tab bar shows the account name; **For You**
   real durations (`_parse_ytm_duration`) + playlists/albums (mixed `kind` items); Now-Playing
   redesigned to a **"terminal boombox"** (ASCII frame + block-char equalizer); **Artist page**
   (`search_artist`/`artist`/`album` bridges → artist card → `ArtistScreen` sections);
   **landscape** layout (list left, now-playing right).
7. **Phase 2 (optional).** MPVKit backend for Opus/exact parity; offline files. Also
   deferred: an artist page on the desktop `master`/`test` branch (user asked "maybe later").

## Distribution (personal use — no App Store needed)

- Free Apple ID signing (7-day expiry) for quick tests.
- **AltStore/SideStore** (auto-refresh every 7 days) or **TrollStore** (permanent,
  only on exploitable iOS versions) for daily use.
- Apple Developer Program ($99/yr) → 1-year signing + TestFlight.
- Public App Store only if distributing to others (full review; YouTube-audio
  apps draw content-policy scrutiny).

## Phase 3 — device run: PASSED ✅ (Milestone 1 complete)

Verified on a physical **iPhone 16 Pro** (iOS, free Apple ID / Personal Team):
embedded Python + yt-dlp resolved YouTube to `_ok=true, ext=m4a, acodec=mp4a.40.2,
itag=140, mime=audio/mp4` from a `googlevideo` URL. Cold resolve ~12s (first-launch
Python import; warm later).

Build/run that worked (`./build.sh device <TEAM> <device_id>`):
- `-allowProvisioningUpdates` auto-created the dev cert (`Apple Development: …`) + the
  `iOS Team Provisioning Profile` and registered the device.
- Prereqs that needed manual phone steps: **Developer Mode** on (Settings → Privacy &
  Security), and **trusting the developer profile** (Settings → General → VPN & Device
  Management) before first launch.

**Milestone 1 (extraction spike) is DONE** — go/no-go is green on host, Simulator, and
device. Next: **Milestone 2** — AVPlayer playback of the m4a URL + `AVAudioSession`
background mode + `MPNowPlayingInfoCenter`/`MPRemoteCommandCenter` lock-screen controls.

Full steps + gotchas: `ios/README.md`.

## Verification (on the Mac mini)

- Build & run in Xcode on a real device (extraction/audio need device, not just
  Simulator).
- Milestone 1 is the go/no-go gate: if `yt-dlp` won't run embedded, reconsider
  (fallback: a tiny self-hosted extraction endpoint, or MPVKit's own ytdl hook).
- Background audio test: start playback, lock the screen / background the app →
  audio continues, lock-screen controls work.

## Open questions

- ~~Can YouTube's JS challenges be solved on iOS (no Deno/JIT)?~~ **Resolved:** yes,
  via a custom yt-dlp JSC provider backed by JavaScriptCore (`JSContext`). See the
  Milestone 1 result above + `ios/spikes/phase0_jsc_spike.py`.
- `python-apple-support` version + `yt-dlp`/`ytmusicapi`/`yt-dlp-ejs` pure-Python deps
  that bundle cleanly (no C-extension surprises) on iOS. Note: `yt-dlp-ejs` is
  **required** now (ships the solver `lib.min.js`/`core.min.js`); both are pure JS data.
- Bridge mechanism: register `_iosbridge.run_js` from Swift via the CPython C-API vs.
  PythonKit. Keep a single long-lived `JSContext` (avoid per-call setup cost).
- AAC availability/quality across tracks; when to force HLS vs progressive.
- Whether to reuse `library.py`/`config.py` via the Python bridge or reimplement
  in Swift (lean: reimplement — keeps the Swift side dependency-light).
