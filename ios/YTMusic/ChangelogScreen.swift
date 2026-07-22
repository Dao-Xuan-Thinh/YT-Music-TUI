import SwiftUI

/// One released version worth of user-facing changes (newest first in `Changelog.entries`).
/// Keep in sync: bump project.yml's version + append an entry with each user-facing change.
struct ChangelogEntry: Identifiable {
    let version: String
    let date: String
    let notes: [String]
    var id: String { version }
}

enum Changelog {
    static let entries: [ChangelogEntry] = [
        ChangelogEntry(version: "1.11", date: "2026-07-22 12:00", notes: [
            "Now-Playing bar is per-device again — resume another device's session from Library → resume (marked ↩)",
            "Fixed the gray box when moving audio output to a Mac",
            "Refined the iPad player layout (fills the column instead of bunching at the top)",
            "All-time top charts + a month/all-time toggle; listening streak, this-year total, most-active weekday",
            "Changelog now shows day & time, and includes the desktop app's history",
        ]),
        ChangelogEntry(version: "1.10", date: "2026-07-21 09:14", notes: [
            "Apple Watch remote: see what's playing and control it (play/pause, next, previous) from your wrist while the phone app is reachable",
        ]),
        ChangelogEntry(version: "1.9", date: "2026-07-20 14:24", notes: [
            "YT MUSIC library section: your real account playlists + Your Likes",
            "Full cross-device sync: likes, playlists and resume sessions travel between desktop and mobile (deletions too)",
            "Now Playing widget with play/pause right on the home screen (iOS 17)",
            "Lock-screen widgets: today's listening at a glance",
            "Top-5 artists and tracks this month in Settings, merged across devices",
            "Background refresh keeps your session alive and stats synced without opening the app",
            "Tokens and the account session moved into the Keychain",
        ]),
        ChangelogEntry(version: "1.8", date: "2026-07-16 13:06", notes: [
            "Settings cleanup: ── section dividers, themes collapsed to one row (opens the picker)",
            "LISTEN STATS redone: totals as tiles, colored sync status, and a per-device breakdown so you can see which device listened how much",
            "↗ YT Music button in the player — opens the current song in the real YouTube Music app",
        ]),
        ChangelogEntry(version: "1.7", date: "2026-07-16 09:45", notes: [
            "The stats widget now follows the app's theme (colors update when you switch themes)",
        ]),
        ChangelogEntry(version: "1.6", date: "2026-07-16 08:42", notes: [
            "Debug log is readable now: per-line entries with colored [tags], red-tinted failures, zebra striping and ── section dividers",
        ]),
        ChangelogEntry(version: "1.5", date: "2026-07-16 08:32", notes: [
            "Dead uploads self-heal: when a saved track's video was removed, the app searches for the song's living copy, plays it, and fixes your library/playlists to point at it",
            "Unavailable videos answer instantly (no more 8s of retrying every tap) and show the real reason",
            "If YouTube throttling comes back after the 30-min window, the reliable pipeline stays on for the whole session",
        ]),
        ChangelogEntry(version: "1.4", date: "2026-07-15 23:56", notes: [
            "Streams that die mid-song (403) now re-resolve themselves and pick up where the audio broke",
            "Prefetched stream links expire after 20 minutes instead of living forever",
            "When YouTube throttles the fast resolver, the app switches to the reliable signed-in pipeline for 30 minutes (no more repeated long gaps)",
            "Silent auto-advance (frozen progress bar until pause/unpause) now un-sticks itself",
        ]),
        ChangelogEntry(version: "1.3", date: "2026-07-15 18:24", notes: [
            "Fixed songs refusing to play (\u{2018}format not available\u{2019}) — they now retry on the web pipeline, signed-in when possible",
            "Fixed the widget being stuck on \u{2018}play something\u{2019} despite existing stats",
            "Updated the extraction engine (yt-dlp 2026.07.04)",
        ]),
        ChangelogEntry(version: "1.2", date: "2026-07-15 12:41", notes: [
            "Listen-time tracking: minutes counted while audio actually plays",
            "Home-screen widget: 7-day bar graph + today / week / all-time totals",
            "Cross-device sync with the desktop app via a private GitHub gist",
            "Settings: LISTEN STATS section (totals, device name, token, sync now)",
        ]),
        ChangelogEntry(version: "1.1", date: "2026-07-13 23:39", notes: [
            "Reorder the queue: hold a row's left edge or its ≡ handle, then drag",
            "Notification on the first launch of a freshly installed build",
        ]),
        ChangelogEntry(version: "1.0", date: "2026-07-13 20:57", notes: [
            "Remembers where you left off — relaunch and tap the bar to resume",
            "Radio no longer restarts the song that's already playing",
            "New themes: paper, mint, lava-lamp, poison; sakura + arctic now animate",
            "Per-theme animated glyphs next to the track title",
            "Light themes now render correctly on every screen",
            "Loading banner while artist pages / albums / radio fetch",
            "Update notice + notification when a newer build is on GitHub",
            "This changelog",
        ]),
        ChangelogEntry(version: "0.5", date: "2026-07-13 11:00", notes: [
            "iPad: full player lives in the landscape layout, lyrics side panel",
            "Plays Music-Premium-only tracks with your signed-in account",
            "Login session auto-refreshes at launch (no more silent expiry)",
            "Debug log in Settings",
            "reinstall.sh: one-command weekly re-sign of all devices",
        ]),
        ChangelogEntry(version: "0.4", date: "2026-07-01 10:05", notes: [
            "Artist pages, albums and playlists (view-first, play explicit)",
            "Radio (endless mix) seeded from the playing track",
            "Synced lyrics with follow-along + translation",
            "Fixed songs stuck fetching forever (timeout + watchdog)",
        ]),
        ChangelogEntry(version: "0.3", date: "2026-06-30 20:07", notes: [
            "Sign in with YouTube (in-app browser or pasted cookies)",
            "Personalized For You feed",
            "Library: liked songs, playlists, recents, resume sessions",
            "15 TUI themes with the color-wave now-playing animation",
        ]),
        ChangelogEntry(version: "0.2", date: "2026-06-27 12:15", notes: [
            "Streaming playback with queue, shuffle, repeat, prefetch",
            "Lock-screen / control-center controls + artwork",
            "Search across YT Music and YouTube",
        ]),
        ChangelogEntry(version: "0.1", date: "2026-06-26 08:38", notes: [
            "Native iOS spike: SwiftUI + embedded Python running yt-dlp on device",
        ]),
    ]

    /// The desktop (Python/Textual) app's history — mirrored here so it's
    /// viewable on mobile via the Mobile/Desktop toggle. Kept in sync with the
    /// desktop app's CHANGELOG (main.py) by hand (different language/branch).
    static let desktopEntries: [ChangelogEntry] = [
        ChangelogEntry(version: "1.6", date: "2026-07-21 09:00", notes: [
            "App no longer goes unresponsive after sitting idle — audio self-recovers with no restart",
            "Expanded stats: all-time top artists/tracks, listening streak, this-year total, most-active weekday",
            "A changelog screen (press V)",
        ]),
        ChangelogEntry(version: "1.5", date: "2026-07-20 14:30", notes: [
            "Gapless auto-advance — the next track is pre-resolved so there is no gap",
            "YT Music tab: your real account playlists + Your Likes on the home screen",
            "Cross-device sync of liked songs, playlists and resume sessions via a private gist",
            "Monthly top charts in the Stats tab",
            "Media keys + OS now-playing panel (macOS / Linux / Windows)",
        ]),
        ChangelogEntry(version: "1.4", date: "2026-07-15 12:13", notes: [
            "Listen-time stats: daily counters + a home Stats tab, synced across devices",
            "Settings is now the sync panel; streaming cookies moved to Account",
        ]),
        ChangelogEntry(version: "1.3", date: "2026-07-13 20:56", notes: [
            "Reorder the queue with K / J (or Shift+arrows)",
            "Radio keeps the currently-playing song going instead of restarting it",
            "4 new + animated light themes with per-theme glyph spinners; update toast",
            "Fixed silent queue-wide skipping",
        ]),
        ChangelogEntry(version: "1.2", date: "2026-07-04 11:33", notes: [
            "Play Music-Premium-only tracks with your signed-in account",
            "Removed the dead OAuth backend; fixed songs stuck 'fetching' forever",
        ]),
        ChangelogEntry(version: "1.1", date: "2026-07-01 10:05", notes: [
            "Artist pages, radio (endless mix) and synced lyrics with follow + translation",
            "Artist and album rows in search results",
        ]),
        ChangelogEntry(version: "1.0", date: "2026-06-27 10:26", notes: [
            "Durable 'Sign in from browser' using live cookies (no more silent expiry)",
            "Fixed the cookie sign-in input freeze; live cookie verification at boot",
        ]),
        ChangelogEntry(version: "0.5", date: "2026-06-26 16:30", notes: [
            "Anti-hang pass: serialized ytmusicapi with per-request timeouts",
            "Fixed the mpv input freeze; added a freeze watchdog",
        ]),
        ChangelogEntry(version: "0.4", date: "2026-06-25 15:11", notes: [
            "Home-screen library management (delete / rename) + a Resume tab",
        ]),
        ChangelogEntry(version: "0.3", date: "2026-06-24 12:48", notes: [
            "Sign in to YouTube + a personalized For You feed",
            "14 custom themes with the animated color-wave; cookie/browser auth",
        ]),
        ChangelogEntry(version: "0.2", date: "2026-06-22 14:44", notes: [
            "Home screen, library/sessions, shuffle/repeat, resume",
            "In-app self-update via git; monochrome glyphs; scroll-stutter fix",
        ]),
        ChangelogEntry(version: "0.1", date: "2026-06-21 19:39", notes: [
            "Baseline TUI: YouTube Music via ytmusicapi (full playlists + artists)",
            "Queue, in-list filter, theme switching; cross-platform mpv IPC",
        ]),
    ]
}

/// Settings → changelog: version history in the hybrid-TUI style.
struct ChangelogScreen: View {
    @ObservedObject private var theme = ThemeManager.shared
    @Environment(\.dismiss) private var dismiss
    @State private var showDesktop = false

    private var shownEntries: [ChangelogEntry] {
        showDesktop ? Changelog.desktopEntries : Changelog.entries
    }

    var body: some View {
        ZStack {
            TUI.bg.ignoresSafeArea()
            VStack(spacing: 0) {
                header
                Picker("", selection: $showDesktop) {
                    Text("Mobile").tag(false)
                    Text("Desktop").tag(true)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, 16).padding(.top, 10)
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        ForEach(shownEntries) { e in
                            VStack(alignment: .leading, spacing: 6) {
                                HStack(spacing: 8) {
                                    Text("v\(e.version)")
                                        .font(TUI.mono(15, .bold)).foregroundStyle(TUI.accent)
                                    Text(e.date).font(TUI.mono(12)).foregroundStyle(TUI.dim)
                                }
                                ForEach(e.notes, id: \.self) { n in
                                    HStack(alignment: .top, spacing: 8) {
                                        Text("·").foregroundStyle(TUI.accent)
                                        Text(n).foregroundStyle(TUI.fg.opacity(0.9))
                                    }
                                    .font(TUI.mono(12))
                                }
                            }
                        }
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .foregroundStyle(TUI.fg).font(TUI.mono()).tint(TUI.accent)
        .preferredColorScheme(theme.current.dark ? .dark : .light)
    }

    private var header: some View {
        HStack {
            Text("changelog").font(TUI.mono(18, .bold)).foregroundStyle(TUI.accent)
            Spacer()
            Text("done").font(TUI.mono(14, .bold)).foregroundStyle(TUI.accent)
                .onTapGesture { dismiss() }
        }
        .padding(14).background(TUI.panel)
    }
}
