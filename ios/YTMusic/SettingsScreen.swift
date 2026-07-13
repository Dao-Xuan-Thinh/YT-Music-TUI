import SwiftUI

/// Settings sheet: theme picker, default search source + volume, clear-library actions,
/// and an about/version section. Hybrid-TUI styled.
struct SettingsScreen: View {
    @ObservedObject var vm: PlayerViewModel
    @ObservedObject private var config = AppConfig.shared
    @ObservedObject private var theme = ThemeManager.shared
    @ObservedObject private var library = LibraryStore.shared
    @ObservedObject private var playback = PlaybackService.shared
    @ObservedObject private var account = AccountStore.shared
    @Environment(\.dismiss) private var dismiss

    @State private var confirmClear: ClearTarget?
    @State private var showAccount = false
    @State private var showDebugLog = false

    enum ClearTarget: String, Identifiable {
        case liked, recent, playlists, sessions
        var id: String { rawValue }
    }

    var body: some View {
        ZStack {
            TUI.bg.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    header
                    accountSection
                    themeSection
                    playbackSection
                    librarySection
                    debugSection
                    aboutSection
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 12)
            }
        }
        .foregroundStyle(TUI.fg)
        .font(TUI.mono())
        .tint(TUI.accent)
        .preferredColorScheme(.dark)
        .alert(item: $confirmClear) { target in
            Alert(
                title: Text("Clear \(target.rawValue)?"),
                message: Text("This can't be undone."),
                primaryButton: .destructive(Text("Clear")) { clear(target) },
                secondaryButton: .cancel())
        }
        .sheet(isPresented: $showAccount) { AccountScreen(vm: vm) }
        .sheet(isPresented: $showDebugLog) { DebugLogScreen() }
    }

    private var accountSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionTitle("ACCOUNT")
            HStack {
                Image(systemName: account.signedIn ? "person.crop.circle.fill" : "person.crop.circle")
                    .foregroundStyle(account.signedIn ? TUI.accent : TUI.dim)
                Text(account.signedIn ? (account.name.isEmpty ? "signed in" : account.name)
                                      : "not signed in")
                    .foregroundStyle(account.signedIn ? TUI.fg : TUI.dim)
                Spacer()
                Text(account.signedIn ? "manage" : "sign in").foregroundStyle(TUI.accent)
            }
            .font(TUI.mono(14))
            .frame(height: 30)
            .contentShape(Rectangle())
            .onTapGesture { showAccount = true }
        }
    }

    // MARK: - Sections

    private var header: some View {
        HStack {
            Text("⚙ settings").font(TUI.mono(18, .bold)).foregroundStyle(TUI.accent)
            Spacer()
            Text("done").font(TUI.mono(14, .bold)).foregroundStyle(TUI.accent)
                .onTapGesture { dismiss() }
        }
    }

    private func sectionTitle(_ s: String) -> some View {
        Text(s).font(TUI.mono(11, .bold)).foregroundStyle(TUI.dim)
    }

    private var themeSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionTitle("THEME")
            ForEach(theme.all) { t in
                HStack(spacing: 10) {
                    Text(t.name == theme.current.name ? "◉" : "○").foregroundStyle(t.accent)
                    Text(t.name).foregroundStyle(t.name == theme.current.name ? TUI.fg : TUI.dim)
                    Spacer()
                    swatches(t)
                }
                .font(TUI.mono(14))
                .frame(height: 30)
                .contentShape(Rectangle())
                .onTapGesture { theme.select(t.name) }
            }
        }
    }

    private func swatches(_ t: AppTheme) -> some View {
        HStack(spacing: 4) {
            ForEach(Array((t.wave ?? [t.accent]).prefix(4).enumerated()), id: \.offset) { _, c in
                RoundedRectangle(cornerRadius: 2).fill(c).frame(width: 14, height: 14)
            }
        }
    }

    private var playbackSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionTitle("PLAYBACK")
            HStack {
                Text("default source").foregroundStyle(TUI.fg)
                Spacer()
                ForEach(SearchSource.allCases, id: \.self) { s in
                    Text(s.rawValue)
                        .font(TUI.mono(13, s == config.defaultSource ? .bold : .regular))
                        .foregroundStyle(s == config.defaultSource ? TUI.accent : TUI.dim)
                        .padding(.horizontal, 6).padding(.vertical, 3)
                        .contentShape(Rectangle())
                        .onTapGesture { config.defaultSource = s; vm.source = s }
                }
            }
            .font(TUI.mono(14))
            HStack(spacing: 10) {
                Text("volume").foregroundStyle(TUI.fg)
                Slider(value: Binding(
                    get: { playback.volume },
                    set: { playback.volume = $0; config.defaultVolume = $0 }), in: 0...1)
                Text("\(Int(playback.volume * 100))%").foregroundStyle(TUI.dim)
                    .frame(width: 42, alignment: .trailing)
            }
            .font(TUI.mono(14))
        }
    }

    private var librarySection: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionTitle("LIBRARY")
            clearRow("liked", library.liked.count, .liked)
            clearRow("recent", library.recent.count, .recent)
            clearRow("playlists", library.playlists.count, .playlists)
            clearRow("sessions", library.sessions.count, .sessions)
        }
    }

    private func clearRow(_ label: String, _ count: Int, _ target: ClearTarget) -> some View {
        HStack {
            Text(label).foregroundStyle(TUI.fg)
            Text("(\(count))").foregroundStyle(TUI.dim)
            Spacer()
            Text("clear")
                .foregroundStyle(count == 0 ? TUI.dim.opacity(0.5) : TUI.warn)
                .onTapGesture { if count > 0 { confirmClear = target } }
        }
        .font(TUI.mono(14))
        .frame(height: 30)
    }

    private var debugSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionTitle("DEBUG")
            HStack {
                Text("debug log").foregroundStyle(TUI.fg)
                Spacer()
                Text("view").foregroundStyle(TUI.accent)
            }
            .font(TUI.mono(14))
            .frame(height: 30)
            .contentShape(Rectangle())
            .onTapGesture { showDebugLog = true }
        }
    }

    private var aboutSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            sectionTitle("ABOUT")
            Text("YouTube Music — native iOS").foregroundStyle(TUI.fg).font(TUI.mono(13))
            Text("version \(appVersion)").foregroundStyle(TUI.dim).font(TUI.mono(12))
            Text("mobile-fork · SwiftUI + embedded yt-dlp").foregroundStyle(TUI.dim).font(TUI.mono(11))
            HStack(spacing: 4) {
                Text("created by").foregroundStyle(TUI.dim)
                Text("Spider In Bathroom").foregroundStyle(TUI.accent)
            }
            .font(TUI.mono(12)).padding(.top, 2)
            Link(destination: URL(string: "https://github.com/Dao-Xuan-Thinh/YT-Music-TUI")!) {
                Text("github.com/Dao-Xuan-Thinh/YT-Music-TUI")
                    .foregroundStyle(TUI.accent).font(TUI.mono(11)).underline()
            }
        }
    }

    private var appVersion: String {
        let v = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "dev"
        let b = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "0"
        return "\(v) (\(b))"
    }

    private func clear(_ target: ClearTarget) {
        switch target {
        case .liked:     library.clearLiked()
        case .recent:    library.clearRecent()
        case .playlists: library.clearPlaylists()
        case .sessions:  library.clearSessions()
        }
    }
}
