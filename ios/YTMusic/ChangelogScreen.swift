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
        ChangelogEntry(version: "1.0", date: "2026-07", notes: [
            "Remembers where you left off — relaunch and tap the bar to resume",
            "Radio no longer restarts the song that's already playing",
            "New themes: paper, mint, lava-lamp, poison; sakura + arctic now animate",
            "Per-theme animated glyphs next to the track title",
            "Light themes now render correctly on every screen",
            "Loading banner while artist pages / albums / radio fetch",
            "Update notice + notification when a newer build is on GitHub",
            "This changelog",
        ]),
        ChangelogEntry(version: "0.5", date: "2026-07", notes: [
            "iPad: full player lives in the landscape layout, lyrics side panel",
            "Plays Music-Premium-only tracks with your signed-in account",
            "Login session auto-refreshes at launch (no more silent expiry)",
            "Debug log in Settings",
            "reinstall.sh: one-command weekly re-sign of all devices",
        ]),
        ChangelogEntry(version: "0.4", date: "2026-07", notes: [
            "Artist pages, albums and playlists (view-first, play explicit)",
            "Radio (endless mix) seeded from the playing track",
            "Synced lyrics with follow-along + translation",
            "Fixed songs stuck fetching forever (timeout + watchdog)",
        ]),
        ChangelogEntry(version: "0.3", date: "2026-06", notes: [
            "Sign in with YouTube (in-app browser or pasted cookies)",
            "Personalized For You feed",
            "Library: liked songs, playlists, recents, resume sessions",
            "15 TUI themes with the color-wave now-playing animation",
        ]),
        ChangelogEntry(version: "0.2", date: "2026-06", notes: [
            "Streaming playback with queue, shuffle, repeat, prefetch",
            "Lock-screen / control-center controls + artwork",
            "Search across YT Music and YouTube",
        ]),
        ChangelogEntry(version: "0.1", date: "2026-06", notes: [
            "Native iOS spike: SwiftUI + embedded Python running yt-dlp on device",
        ]),
    ]
}

/// Settings → changelog: version history in the hybrid-TUI style.
struct ChangelogScreen: View {
    @ObservedObject private var theme = ThemeManager.shared
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            TUI.bg.ignoresSafeArea()
            VStack(spacing: 0) {
                header
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        ForEach(Changelog.entries) { e in
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
