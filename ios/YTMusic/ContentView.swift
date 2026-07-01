import SwiftUI

struct ContentView: View {
    @StateObject private var vm = PlayerViewModel()
    @ObservedObject private var playback = PlaybackService.shared
    @ObservedObject private var library = LibraryStore.shared
    @ObservedObject private var theme = ThemeManager.shared
    @ObservedObject private var account = AccountStore.shared
    @Environment(\.scenePhase) private var scenePhase

    @State private var query = ""
    @FocusState private var searchFocused: Bool

    @State private var scrub: Double = 0
    @State private var scrubbing = false
    @State private var dragStartHighlight: Int?
    @State private var navMode = false   // true while long-press-drag owns the list

    // Playlist save / rename prompts.
    @State private var showSavePlaylist = false
    @State private var newPlaylistName = ""
    @State private var renameTarget: String?
    @State private var renameName = ""
    @State private var showNowPlaying = false
    @State private var showSettings = false
    @State private var showThemePicker = false

    private let rowHeight: CGFloat = 30

    var body: some View {
        ZStack {
            TUI.bg.ignoresSafeArea()
            VStack(spacing: 8) {
                tabBar
                if vm.tab == .search { searchRow }
                if vm.tab == .library { librarySections }
                if vm.tab == .foryou { forYouHeader }
                if vm.tab == .queue, !vm.queue.isEmpty { queueActions }
                TUIDivider()
                list
                TUIDivider()
                nowPlaying
                footer
            }
            .padding(.horizontal, 12)
            .padding(.top, 6)
        }
        .foregroundStyle(TUI.fg)
        .font(TUI.mono())
        .tint(TUI.accent)
        .preferredColorScheme(theme.current.dark ? .dark : .light)
        .onChange(of: playback.position) { p in if !scrubbing { scrub = p } }
        .onChange(of: scenePhase) { phase in
            if phase == .background { vm.saveCurrentSession() }
        }
        .onChange(of: vm.tab) { t in if t == .foryou { vm.loadHome() } }
        .onAppear { AccountStore.shared.restore() }
        .alert("Save playlist", isPresented: $showSavePlaylist) {
            TextField("name", text: $newPlaylistName)
            Button("Save") { vm.saveQueueAsPlaylist(name: newPlaylistName) }
            Button("Cancel", role: .cancel) {}
        }
        .alert("Rename playlist", isPresented: Binding(
            get: { renameTarget != nil },
            set: { if !$0 { renameTarget = nil } })
        ) {
            TextField("name", text: $renameName)
            Button("Rename") {
                if let t = renameTarget { library.renamePlaylist(old: t, new: renameName) }
                renameTarget = nil
            }
            Button("Cancel", role: .cancel) { renameTarget = nil }
        }
        .fullScreenCover(isPresented: $showNowPlaying) {
            NowPlayingScreen(vm: vm, playback: playback)
        }
        .sheet(isPresented: $showSettings) {
            SettingsScreen(vm: vm)
        }
        .sheet(isPresented: $showThemePicker) {
            ThemePickerSheet()
        }
    }

    // MARK: - Tab bar

    private var tabBar: some View {
        HStack(spacing: 12) {
            tabLabel("FOR YOU", .foryou)
            tabLabel("SEARCH", .search)
            tabLabel("QUEUE", .queue)
            tabLabel("LIBRARY", .library)
            Spacer()
            if account.signedIn {
                Text("♥ \(account.name.isEmpty ? "you" : account.name)")
                    .foregroundStyle(TUI.accent).lineLimit(1)
                    .onTapGesture { showSettings = true }
            } else {
                Text("♥ \(library.liked.count)")
                    .foregroundStyle(TUI.accent)
                    .onTapGesture {
                        vm.tab = .library; vm.librarySection = .liked
                        vm.openedPlaylist = nil; vm.highlightIndex = 0
                    }
            }
        }
        .font(TUI.mono(13, .bold))
    }

    private func tabLabel(_ title: String, _ t: Tab) -> some View {
        let active = vm.tab == t
        return Text(active ? "[ \(title) ]" : title.lowercased())
            .foregroundStyle(active ? TUI.accent : TUI.dim)
            .onTapGesture { vm.tab = t; vm.openedPlaylist = nil; vm.highlightIndex = 0 }
    }

    // MARK: - Library sub-sections + queue actions

    private var librarySections: some View {
        HStack(spacing: 14) {
            ForEach(LibrarySection.allCases, id: \.self) { s in
                let active = vm.librarySection == s
                Text(active ? "[\(s.rawValue)]" : s.rawValue)
                    .foregroundStyle(active ? TUI.accent : TUI.dim)
                    .onTapGesture { vm.librarySection = s; vm.openedPlaylist = nil; vm.highlightIndex = 0 }
            }
            Spacer()
        }
        .font(TUI.mono(12))
    }

    private var queueActions: some View {
        HStack {
            Spacer()
            Text("+pl")
                .font(TUI.mono(12, .bold))
                .foregroundStyle(TUI.accent)
                .onTapGesture { newPlaylistName = ""; showSavePlaylist = true }
        }
    }

    private var forYouHeader: some View {
        HStack(spacing: 8) {
            Text("for you").foregroundStyle(TUI.dim)
            if vm.homeLoading { ProgressView().controlSize(.mini).tint(TUI.accent) }
            Spacer()
            Image(systemName: "arrow.clockwise").foregroundStyle(TUI.accent)
                .onTapGesture { vm.loadHome(force: true) }
        }
        .font(TUI.mono(12))
    }

    // MARK: - Search

    private var searchRow: some View {
        HStack(spacing: 6) {
            Text("/")
                .foregroundStyle(TUI.accent)
                .contentShape(Rectangle())
                .onTapGesture { query = ""; searchFocused = true }   // tap to clear
            TextField("", text: $query,
                      prompt: Text("search or paste url").foregroundColor(TUI.dim))
                .focused($searchFocused)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.search)
                .onSubmit { vm.submit(query); searchFocused = false }
            if vm.searching || vm.resolving {
                ProgressView().controlSize(.small).tint(TUI.accent)
            }
            Text("src:\(vm.source.rawValue)")
                .font(TUI.mono(12))
                .foregroundStyle(TUI.accent)
                .onTapGesture { vm.cycleSource() }
        }
        .padding(8)
        .background(TUI.panel)
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(TUI.dim.opacity(0.4)))
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    // MARK: - List (tracks / playlists / sessions) with gesture navigation

    private var list: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    listBody
                }
            }
            .scrollDisabled(navMode)
            .simultaneousGesture(highlightDrag)
            .onChange(of: vm.highlightIndex) { i in
                guard vm.displayed.indices.contains(i) else { return }
                withAnimation(.easeOut(duration: 0.1)) {
                    proxy.scrollTo(vm.displayed[i].id, anchor: .center)
                }
            }
        }
        .frame(maxHeight: .infinity)
    }

    @ViewBuilder private var listBody: some View {
        if vm.tab == .library && vm.librarySection == .playlists {
            if vm.openedPlaylist != nil { playlistDetail } else { playlistRows }
        } else if vm.tab == .library && vm.librarySection == .resume {
            sessionRows
        } else {
            if vm.tab == .foryou && vm.homeLoading && vm.home.isEmpty {
                HStack { Spacer(); ProgressView().tint(TUI.accent); Spacer() }
                    .padding(.vertical, 24)
            } else if let e = vm.errorMsg, vm.displayed.isEmpty {
                Text(e).foregroundStyle(TUI.warn).padding(.vertical, 8)
            } else if vm.displayed.isEmpty {
                Text(emptyHint).foregroundStyle(TUI.dim).padding(.vertical, 8)
            }
            ForEach(Array(vm.displayed.enumerated()), id: \.element.id) { idx, r in
                trackRow(idx, r)
            }
        }
    }

    private var emptyHint: String {
        switch vm.tab {
        case .search: return ""
        case .queue:  return "queue is empty"
        case .foryou: return "tap ⟳ to load your feed"
        case .library:
            switch vm.librarySection {
            case .liked:  return "no liked tracks yet — ♥ one while it plays"
            case .recent: return "nothing played yet"
            default:      return ""
            }
        }
    }

    // A track row, plus a library context menu (unlike / remove) when in the Library tab.
    @ViewBuilder private func trackRow(_ idx: Int, _ r: SearchResult) -> some View {
        if vm.tab == .library {
            row(idx, r).contextMenu {
                switch vm.librarySection {
                case .recent:
                    Button { library.toggleLike(r) } label: {
                        Label(library.isLiked(r.id) ? "Unlike" : "Like", systemImage: "heart")
                    }
                    Button(role: .destructive) { library.removeRecent(r.id) } label: {
                        Label("Remove", systemImage: "trash")
                    }
                case .liked:
                    Button(role: .destructive) { library.toggleLike(r) } label: {
                        Label("Unlike", systemImage: "heart.slash")
                    }
                default:   // playlist detail
                    Button { library.toggleLike(r) } label: {
                        Label(library.isLiked(r.id) ? "Unlike" : "Like", systemImage: "heart")
                    }
                }
            }
        } else {
            row(idx, r)
        }
    }

    private func row(_ idx: Int, _ r: SearchResult) -> some View {
        let playing = (r.id == vm.playingID)
        let highlighted = (idx == vm.highlightIndex)
        return HStack(spacing: 8) {
            Text(playing ? "▸" : (r.isPlaylist ? "≡" : (highlighted ? "›" : " ")))
                .foregroundStyle(TUI.accent)
            Text(String(format: "%2d", idx + 1)).foregroundStyle(TUI.dim)
            if playing {
                WaveText(text: r.title, palette: theme.current.wave, font: TUI.mono(13),
                         fallback: TUI.accent, active: playback.isPlaying, lineLimit: 1)
            } else {
                Text(r.title).foregroundStyle(TUI.fg).lineLimit(1).truncationMode(.tail)
            }
            Spacer(minLength: 6)
            Text(r.isPlaylist ? "playlist" : timeString(Double(r.duration)))
                .foregroundStyle(TUI.dim)
        }
        .font(TUI.mono(13))
        .frame(height: rowHeight)
        .background(highlighted ? TUI.accent.opacity(0.12) : .clear)
        .contentShape(Rectangle())
        .onTapGesture(count: 2) { vm.tab = (vm.tab == .search ? .queue : .search) }
        .onTapGesture { playRow(idx) }
    }

    private func playRow(_ idx: Int) {
        // A playlist/album row (e.g. in For You) opens rather than plays.
        if vm.displayed.indices.contains(idx), vm.displayed[idx].isPlaylist {
            vm.openPlaylist(id: vm.displayed[idx].playlistId ?? vm.displayed[idx].id)
            return
        }
        switch vm.tab {
        case .search:           vm.playFromResults(at: idx)
        case .queue:            vm.playFromQueue(at: idx)
        case .library, .foryou: vm.playList(vm.displayed, at: idx)
        }
    }

    // Playlist name rows (Library → playlists). Tap opens the playlist; play is explicit.
    @ViewBuilder private var playlistRows: some View {
        if library.playlists.isEmpty {
            Text("no playlists — save a queue with +pl")
                .foregroundStyle(TUI.dim).padding(.vertical, 8)
        }
        ForEach(library.playlists) { p in
            HStack(spacing: 8) {
                Text("≡").foregroundStyle(TUI.accent)
                Text(p.name).foregroundStyle(TUI.fg).lineLimit(1)
                Spacer(minLength: 6)
                Text("\(p.tracks.count)").foregroundStyle(TUI.dim)
                Image(systemName: "play.fill")
                    .font(TUI.mono(11)).foregroundStyle(TUI.accent)
                    .contentShape(Rectangle())
                    .onTapGesture { vm.playPlaylist(p) }
            }
            .font(TUI.mono(13))
            .frame(height: rowHeight)
            .contentShape(Rectangle())
            .onTapGesture { vm.openedPlaylist = p.name; vm.highlightIndex = 0 }   // open, don't play
            .contextMenu {
                Button { vm.playPlaylist(p) } label: { Label("Play", systemImage: "play") }
                Button { renameTarget = p.name; renameName = p.name } label: {
                    Label("Rename", systemImage: "pencil")
                }
                Button(role: .destructive) { library.deletePlaylist(name: p.name) } label: {
                    Label("Delete", systemImage: "trash")
                }
            }
        }
    }

    // An opened playlist's tracks, with a back row + play-all. Tapping a track plays the
    // playlist from there.
    @ViewBuilder private var playlistDetail: some View {
        let name = vm.openedPlaylist ?? ""
        HStack(spacing: 8) {
            Text("‹ back").foregroundStyle(TUI.accent)
                .contentShape(Rectangle())
                .onTapGesture { vm.openedPlaylist = nil; vm.highlightIndex = 0 }
            Spacer(minLength: 6)
            Text(name).foregroundStyle(TUI.dim).lineLimit(1)
            Spacer(minLength: 6)
            Text("▶ play").foregroundStyle(TUI.accent)
                .contentShape(Rectangle())
                .onTapGesture { if let p = library.playlist(named: name) { vm.playPlaylist(p) } }
        }
        .font(TUI.mono(12, .bold))
        .frame(height: rowHeight)

        if vm.displayed.isEmpty {
            Text("empty playlist").foregroundStyle(TUI.dim).padding(.vertical, 8)
        }
        ForEach(Array(vm.displayed.enumerated()), id: \.element.id) { idx, r in
            trackRow(idx, r)
        }
    }

    // Saved-session rows (Library → resume).
    @ViewBuilder private var sessionRows: some View {
        if library.sessions.isEmpty {
            Text("no saved sessions").foregroundStyle(TUI.dim).padding(.vertical, 8)
        }
        ForEach(library.sessions) { s in
            HStack(spacing: 8) {
                Text("⏵").foregroundStyle(TUI.accent)
                VStack(alignment: .leading, spacing: 1) {
                    Text(s.title).foregroundStyle(TUI.fg).lineLimit(1).font(TUI.mono(13))
                    Text("\(s.queue.count) tracks · \(timeString(s.position))")
                        .foregroundStyle(TUI.dim).font(TUI.mono(10))
                }
                Spacer(minLength: 6)
            }
            .frame(height: rowHeight + 6)
            .contentShape(Rectangle())
            .onTapGesture { vm.restore(s) }
            .contextMenu {
                Button(role: .destructive) { library.deleteSession(id: s.id) } label: {
                    Label("Delete", systemImage: "trash")
                }
            }
        }
    }

    /// Long-press-then-drag moves the highlighter; scrolling is suspended while it's active
    /// so the two don't fight.
    private var highlightDrag: some Gesture {
        LongPressGesture(minimumDuration: 0.25)
            .sequenced(before: DragGesture(minimumDistance: 0))
            .onChanged { value in
                if case .second(true, let drag?) = value {
                    navMode = true
                    if dragStartHighlight == nil { dragStartHighlight = vm.highlightIndex }
                    let delta = Int((drag.translation.height / rowHeight).rounded())
                    vm.highlightIndex = min(max((dragStartHighlight ?? 0) + delta, 0),
                                            max(vm.displayed.count - 1, 0))
                }
            }
            .onEnded { _ in dragStartHighlight = nil; navMode = false }
    }

    // MARK: - Now playing

    private var nowPlaying: some View {
        VStack(spacing: 6) {
            HStack(spacing: 10) {
                HStack(spacing: 10) {
                    AsyncImage(url: playback.current?.thumbnailURL) { phase in
                        if case .success(let img) = phase { img.resizable().scaledToFill() }
                        else { TUI.panel }
                    }
                    .frame(width: 48, height: 48)
                    .clipShape(RoundedRectangle(cornerRadius: 4))
                    VStack(alignment: .leading, spacing: 2) {
                        WaveText(text: playback.current?.title ?? "nothing playing",
                                 palette: theme.current.wave,
                                 font: TUI.mono(14, .bold),
                                 fallback: TUI.fg,
                                 active: playback.isPlaying && playback.current != nil,
                                 lineLimit: 1)
                        Text(playback.current?.uploader ?? " ")
                            .font(TUI.mono(12)).foregroundStyle(TUI.dim).lineLimit(1)
                    }
                    Spacer()
                }
                .contentShape(Rectangle())
                .onTapGesture { if playback.current != nil { showNowPlaying = true } }   // expand
                Button { vm.toggleLikeCurrent() } label: {
                    Image(systemName: likedNow ? "heart.fill" : "heart").font(.title3)
                }
                .foregroundStyle(TUI.accent)
                .disabled(vm.currentResult == nil)
            }

            Slider(value: $scrub, in: 0...max(playback.duration, 1), onEditingChanged: { ed in
                scrubbing = ed
                if !ed { playback.seek(to: scrub) }
            })
            .disabled(playback.current == nil)

            HStack {
                Text(timeString(scrub)).font(TUI.mono(11)).foregroundStyle(TUI.dim)
                Spacer()
                Text(timeString(playback.duration)).font(TUI.mono(11)).foregroundStyle(TUI.dim)
            }

            HStack(spacing: 48) {
                Button { vm.playPrevious() } label: { Image(systemName: "backward.end.fill").font(.title2) }
                Button { playback.togglePlayPause() } label: {
                    Image(systemName: playback.isPlaying ? "pause.fill" : "play.fill").font(.largeTitle)
                }
                Button { vm.playNext() } label: { Image(systemName: "forward.end.fill").font(.title2) }
            }
            .foregroundStyle(TUI.accent)
            .disabled(playback.current == nil)
            .padding(.top, 2)
        }
    }

    private var likedNow: Bool {
        guard let r = vm.currentResult else { return false }
        return library.isLiked(r.id)
    }

    // MARK: - Footer

    private var footer: some View {
        let i = (vm.queueIndex ?? -1) + 1
        return HStack(spacing: 6) {
            Text("shuf:\(vm.shuffle ? "on" : "off")")
                .foregroundStyle(vm.shuffle ? TUI.accent : TUI.dim)
                .onTapGesture { vm.toggleShuffle() }
            sep
            Text("rep:\(vm.repeatMode.rawValue)")
                .foregroundStyle(vm.repeatMode == .off ? TUI.dim : TUI.accent)
                .onTapGesture { vm.cycleRepeat() }
            sep
            Text("q:\(i)/\(vm.queue.count)").foregroundStyle(TUI.dim)
            sep
            Text("\(Int(playback.volume * 100))%").foregroundStyle(TUI.dim)
            sep
            Text(theme.current.name).foregroundStyle(TUI.accent)
                .onTapGesture { showThemePicker = true }
            Spacer()
            Image(systemName: "gearshape").foregroundStyle(TUI.dim)
                .onTapGesture { showSettings = true }
        }
        .font(TUI.mono(11))
        .padding(.vertical, 4)
    }

    private var sep: some View { Text("·").foregroundStyle(TUI.dim.opacity(0.6)) }

    private func timeString(_ s: Double) -> String {
        guard s.isFinite, s >= 0 else { return "0:00" }
        let t = Int(s)
        return String(format: "%d:%02d", t / 60, t % 60)
    }
}
