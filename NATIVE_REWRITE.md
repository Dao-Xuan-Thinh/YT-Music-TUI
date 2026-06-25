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

## Milestones

1. **Spike — extraction on device.** Xcode project + `python-apple-support`;
   prove `yt-dlp` resolves a video to an `m4a` URL on a real device. (Riskiest
   piece — do it first.)
2. **Playback.** `AVPlayer` plays that URL; `AVAudioSession` background mode;
   lock-screen controls via `MPNowPlayingInfoCenter`/`MPRemoteCommandCenter`.
3. **Search + results UI.** SwiftUI search → bridge `search()` → results list →
   tap to play; queue + auto-advance.
4. **Library.** Liked / playlists / recent / sessions (`LibraryStore`), mirroring
   the desktop home tabs; resume.
5. **Polish.** Now-playing screen, artwork, settings, themes.
6. **Phase 2 (optional).** MPVKit backend for Opus/exact parity; offline files.

## Distribution (personal use — no App Store needed)

- Free Apple ID signing (7-day expiry) for quick tests.
- **AltStore/SideStore** (auto-refresh every 7 days) or **TrollStore** (permanent,
  only on exploitable iOS versions) for daily use.
- Apple Developer Program ($99/yr) → 1-year signing + TestFlight.
- Public App Store only if distributing to others (full review; YouTube-audio
  apps draw content-policy scrutiny).

## Verification (on the Mac mini)

- Build & run in Xcode on a real device (extraction/audio need device, not just
  Simulator).
- Milestone 1 is the go/no-go gate: if `yt-dlp` won't run embedded, reconsider
  (fallback: a tiny self-hosted extraction endpoint, or MPVKit's own ytdl hook).
- Background audio test: start playback, lock the screen / background the app →
  audio continues, lock-screen controls work.

## Open questions to resolve on first Mac session

- `python-apple-support` version + `yt-dlp`/`ytmusicapi` pure-Python deps that
  bundle cleanly (no C-extension surprises) on iOS.
- AAC availability/quality across tracks; when to force HLS vs progressive.
- Whether to reuse `library.py`/`config.py` via the Python bridge or reimplement
  in Swift (lean: reimplement — keeps the Swift side dependency-light).
