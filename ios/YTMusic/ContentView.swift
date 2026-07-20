import SwiftUI

struct ContentView: View {
    @StateObject private var vm = PlayerViewModel()
    @ObservedObject private var playback = PlaybackService.shared
    @ObservedObject private var library = LibraryStore.shared
    @ObservedObject private var theme = ThemeManager.shared
    @ObservedObject private var account = AccountStore.shared
    @ObservedObject private var updater = UpdateChecker.shared
    @Environment(\.scenePhase) private var scenePhase

    @State private var query = ""
    @FocusState private var searchFocused: Bool

    @State private var scrub: Double = 0
    @State private var scrubbing = false
    @State private var dragStartHighlight: Int?
    @State private var navMode = false   // true while long-press-drag owns the list
    @State private var dragQueueIndex: Int?   // queue row being drag-reordered (live index)
    @State private var dragStartQueue: Int?   // where that drag began

    // Playlist save / rename prompts.
    @State private var showSavePlaylist = false
    @State private var newPlaylistName = ""
    @State private var renameTarget: String?
    @State private var renameName = ""
    @State private var showNowPlaying = false
    @State private var showSettings = false
    @State private var showThemePicker = false
    @State private var showLyricsPanel = false   // iPad landscape: right panel → lyrics

    private let rowHeight: CGFloat = 30
    /// iPad landscape integrates the full player into the root layout (no fullscreen
    /// cover there); iPhone — including regular-width Max models — keeps the cover.
    private let isPad = UIDevice.current.userInterfaceIdiom == .pad

    var body: some View {
        ZStack {
            TUI.bg.ignoresSafeArea()
            GeometryReader { geo in
                if geo.size.width > geo.size.height {
                    landscapeStack
                } else {
                    portraitStack
                }
            }
            .padding(.horizontal, 12)
            .padding(.top, 6)
        }
        .overlay(alignment: .top) { loadingBanner }
        .foregroundStyle(TUI.fg)
        .font(TUI.mono())
        .tint(TUI.accent)
        .preferredColorScheme(theme.current.dark ? .dark : .light)
        .onChange(of: playback.position) { p in if !scrubbing { scrub = p } }
        .onChange(of: scenePhase) { phase in
            // .inactive too: an app-switcher swipe-kill passes through .inactive but can
            // skip .background, losing the resume snapshot.
            if phase == .background || phase == .inactive {
                vm.saveCurrentSession()
                StatsStore.shared.flush(reloadWidget: true)
            }
            if phase == .active {
                UpdateChecker.shared.check()
                StatsStore.shared.sync()   // self-throttled (10 min)
            }
        }
        .onChange(of: vm.tab) { t in if t == .foryou { vm.loadHome() } }
        // Now Playing widget's iOS-16 fallback (no interactive buttons there):
        // the whole widget deep-links here and toggles/resumes.
        .onOpenURL { url in
            guard url.scheme == "ytmtui", url.host == "playpause" else { return }
            if playback.current != nil {
                playback.togglePlayPause()
            } else if vm.pendingResume != nil {
                vm.resumePending()
            }
        }
        .onAppear {
            AccountStore.shared.restore()
            vm.armResume()   // remember where you left off (tap the bar to resume)
            UpdateChecker.shared.check()
            UpdateChecker.shared.announceBuildIfNew()
            StatsStore.shared.sync()   // pull other devices' listen time
            WatchLink.shared.vm = vm   // watch remote (no-op without a watch)
            WatchLink.shared.start()
        }
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
        .fullScreenCover(isPresented: Binding(
            get: { vm.artistPage != nil },
            set: { if !$0 { vm.artistPage = nil } })
        ) {
            if let page = vm.artistPage { ArtistScreen(vm: vm, page: page) }
        }
        // When an artist page is up, its own nested cover presents the collection
        // (a sibling cover here would silently wait until the artist page closed).
        .fullScreenCover(isPresented: Binding(
            get: { vm.openedCollection && vm.artistPage == nil },
            set: { if !$0 { vm.openedCollection = false } })
        ) {
            CollectionScreen(vm: vm, title: vm.collectionTitle, tracks: vm.collectionTracks)
        }
    }

    /// Slim top banner while a slow fetch runs (artist page, album/playlist, radio, search)
    /// so long loads never look like a frozen app.
    private var isLoadingSomething: Bool {
        vm.artistLoading || vm.collectionLoading || vm.searching
    }

    @ViewBuilder private var loadingBanner: some View {
        if isLoadingSomething {
            HStack(spacing: 8) {
                ProgressView().tint(TUI.accent).scaleEffect(0.7)
                Text(vm.loadingLabel.isEmpty ? "loading…" : vm.loadingLabel)
                    .font(TUI.mono(12, .bold)).foregroundStyle(TUI.fg)
                    .lineLimit(1)
            }
            .padding(.vertical, 6).padding(.horizontal, 14)
            .background(TUI.panel.opacity(0.95))
            .clipShape(Capsule())
            .overlay(Capsule().stroke(TUI.accent.opacity(0.5)))
            .padding(.top, 4)
            .transition(.move(edge: .top).combined(with: .opacity))
            .animation(.easeInOut(duration: 0.2), value: isLoadingSomething)
            .allowsHitTesting(false)
        }
    }

    // MARK: - Orientation layouts

    /// The tab bar + per-tab sub-header rows (shared by both orientations).
    @ViewBuilder private var browseHeader: some View {
        accountLine
        tabBar
        if vm.tab == .search { searchRow }
        if vm.tab == .search, let hit = vm.artistHit { artistCard(hit) }
        if vm.tab == .library { librarySections }
        if vm.tab == .foryou { forYouHeader }
        if vm.tab == .queue, !vm.queue.isEmpty { queueActions }
    }

    private var portraitStack: some View {
        VStack(spacing: 8) {
            browseHeader
            TUIDivider()
            list
            TUIDivider()
            nowPlaying
            footer(showLyricsButton: false)
        }
    }

    /// Landscape: now-playing (square cover + controls) on the LEFT, browse list on the RIGHT.
    /// The left column is intentionally narrower (~38%) so the right column keeps enough width
    /// for the 4 tabs; the cover is sized to fit both the column width and the visible height.
    /// On iPad the left column IS the full player (equalizer, toggles, radio, volume — the
    /// fullscreen cover is retired there) and the right panel can swap to lyrics.
    private var landscapeStack: some View {
        GeometryReader { geo in
            let leftW = geo.size.width * 0.38
            // On iPad leave room below the cover for the equalizer + extra control rows.
            let coverSide = min(leftW - 8, geo.size.height * (isPad ? 0.42 : 0.5))
            VStack(spacing: 6) {
                HStack(alignment: .top, spacing: 16) {
                    nowPlayingLandscape(coverSide: coverSide)
                        .frame(width: leftW)
                    VStack(spacing: 6) {
                        if isPad && showLyricsPanel {
                            lyricsSidePanel
                        } else {
                            browseHeader
                            TUIDivider()
                            list
                        }
                    }
                    .frame(maxWidth: .infinity)
                }
                footer(showLyricsButton: isPad)
            }
        }
    }

    /// Landscape now-playing: a square (1:1) cover, then title, scrubber, and transport.
    /// iPad adds the fullscreen player's remaining features inline.
    private func nowPlayingLandscape(coverSide: CGFloat) -> some View {
        VStack(spacing: 10) {
            AsyncImage(url: playback.current?.thumbnailURL) { phase in
                if case .success(let img) = phase { img.resizable().scaledToFill() }
                else { TUI.panel.overlay(Text("♪").font(.system(size: 56)).foregroundStyle(TUI.dim)) }
            }
            .frame(width: coverSide, height: coverSide)   // fixed square → fills, no letterbox
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(TUI.dim.opacity(0.3)))
            .contentShape(Rectangle())
            // iPhone: tap expands to the fullscreen player. iPad: the player lives here.
            .onTapGesture { if !isPad, playback.current != nil { showNowPlaying = true } }
            .frame(maxWidth: .infinity)   // center the cover in the column

            if isPad {
                Equalizer(playback: playback, active: playback.isPlaying,
                          palette: theme.current.wave ?? [TUI.accent])
                    .frame(maxWidth: .infinity, minHeight: 30, maxHeight: 30)
            }

            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    WaveText(text: playback.current?.title ?? "nothing playing",
                             palette: theme.current.wave, font: TUI.mono(15, .bold),
                             fallback: TUI.fg,
                             active: playback.isPlaying && playback.current != nil, lineLimit: 1)
                    artistLabel(font: TUI.mono(12))
                }
                Spacer()
                Button { vm.toggleLikeCurrent() } label: {
                    Image(systemName: likedNow ? "heart.fill" : "heart").font(.title3)
                }
                .foregroundStyle(TUI.accent).disabled(vm.currentResult == nil)
            }

            Slider(value: $scrub, in: 0...max(playback.duration, 1), onEditingChanged: { ed in
                scrubbing = ed
                if !ed { playback.seek(to: scrub) }
            })
            .disabled(playback.current == nil)

            if isPad {
                HStack {
                    Text(timeString(scrub)).font(TUI.mono(11)).foregroundStyle(TUI.dim)
                    Spacer()
                    Text(timeString(playback.duration)).font(TUI.mono(11)).foregroundStyle(TUI.dim)
                }
            }

            HStack(spacing: 44) {
                Button { vm.playPrevious() } label: { Image(systemName: "backward.end.fill").font(.title3) }
                Button { playback.togglePlayPause() } label: {
                    Image(systemName: playback.isPlaying ? "pause.fill" : "play.fill").font(.largeTitle)
                }
                Button { vm.playNext() } label: { Image(systemName: "forward.end.fill").font(.title3) }
            }
            .foregroundStyle(TUI.accent).disabled(playback.current == nil)

            if isPad {
                HStack(spacing: 30) {
                    Text("shuffle")
                        .foregroundStyle(vm.shuffle ? TUI.accent : TUI.dim)
                        .onTapGesture { vm.toggleShuffle() }
                    Text("repeat:\(vm.repeatMode.rawValue)")
                        .foregroundStyle(vm.repeatMode == .off ? TUI.dim : TUI.accent)
                        .onTapGesture { vm.cycleRepeat() }
                    Text("∞ radio")
                        .foregroundStyle(vm.currentResult == nil ? TUI.dim : TUI.accent)
                        .onTapGesture { vm.startRadio() }
                }
                .font(TUI.mono(13, .bold))
                .padding(.top, 2)

                HStack(spacing: 10) {
                    Image(systemName: "speaker.fill").font(.caption).foregroundStyle(TUI.dim)
                    Slider(value: $playback.volume, in: 0...1)
                    Image(systemName: "speaker.wave.3.fill").font(.caption).foregroundStyle(TUI.dim)
                    Text("\(Int(playback.volume * 100))%").font(TUI.mono(11)).foregroundStyle(TUI.dim)
                        .frame(width: 38, alignment: .trailing)
                }
            }
        }
    }

    /// iPad landscape right panel in lyrics mode: header with a way back to browse,
    /// then the shared following/translatable lyrics view.
    private var lyricsSidePanel: some View {
        VStack(spacing: 6) {
            HStack {
                WaveText(text: playback.current?.title ?? "nothing playing",
                         palette: theme.current.wave, font: TUI.mono(13, .bold),
                         fallback: TUI.fg,
                         active: playback.isPlaying && playback.current != nil, lineLimit: 1)
                Spacer()
                Text("✕ browse").font(TUI.mono(12, .bold)).foregroundStyle(TUI.dim)
                    .onTapGesture { showLyricsPanel = false }
            }
            TUIDivider()
            LyricsPanel(vm: vm, playback: playback)
        }
    }

    /// A tappable artist result card shown above the search list.
    private func artistCard(_ hit: ArtistHit) -> some View {
        HStack(spacing: 10) {
            AsyncImage(url: hit.thumbnailURL) { phase in
                if case .success(let img) = phase { img.resizable().scaledToFill() }
                else { TUI.panel }
            }
            .frame(width: 44, height: 44)
            .clipShape(Circle())
            .overlay(Circle().stroke(TUI.accent.opacity(0.5)))
            VStack(alignment: .leading, spacing: 2) {
                Text("ARTIST").font(TUI.mono(10, .bold)).foregroundStyle(TUI.dim)
                Text(hit.name).font(TUI.mono(15, .bold)).foregroundStyle(TUI.accent).lineLimit(1)
            }
            Spacer()
            if vm.artistLoading { ProgressView().controlSize(.small).tint(TUI.accent) }
            else { Image(systemName: "chevron.right").foregroundStyle(TUI.accent) }
        }
        .padding(8)
        .background(TUI.panel)
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(TUI.accent.opacity(0.4)))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .contentShape(Rectangle())
        .onTapGesture { vm.openArtist(hit) }
    }

    // MARK: - Tab bar

    /// A slim line above the tabs showing the signed-in account (kept off the tab row so a
    /// long name can't squeeze the tabs into wrapping). Only present when signed in.
    @ViewBuilder private var accountLine: some View {
        if account.signedIn {
            HStack(spacing: 6) {
                Text("♥ \(account.name.isEmpty ? "you" : account.name)")
                    .font(TUI.mono(11, .bold)).foregroundStyle(TUI.accent)
                    .lineLimit(1).truncationMode(.tail)
                Spacer()
            }
            .contentShape(Rectangle())
            .onTapGesture { showSettings = true }
        }
    }

    private var tabBar: some View {
        HStack(spacing: 12) {
            tabLabel("FOR YOU", .foryou)
            tabLabel("SEARCH", .search)
            tabLabel("QUEUE", .queue)
            tabLabel("LIBRARY", .library)
            Spacer()
            Text("♥ \(library.liked.count)")
                .foregroundStyle(TUI.accent)
                .onTapGesture {
                    vm.tab = .library; vm.librarySection = .liked
                    vm.openedPlaylist = nil; vm.highlightIndex = 0
                }
        }
        .font(TUI.mono(13, .bold))
    }

    private func tabLabel(_ title: String, _ t: Tab) -> some View {
        let active = vm.tab == t
        return Text(active ? "[ \(title) ]" : title.lowercased())
            .foregroundStyle(active ? TUI.accent : TUI.dim)
            .lineLimit(1).fixedSize(horizontal: true, vertical: false)   // never wrap
            .onTapGesture { vm.tab = t; vm.openedPlaylist = nil; vm.highlightIndex = 0 }
    }

    // MARK: - Library sub-sections + queue actions

    private var librarySections: some View {
        HStack(spacing: 14) {
            ForEach(LibrarySection.allCases, id: \.self) { s in
                let active = vm.librarySection == s
                Text(active ? "[\(s.rawValue)]" : s.rawValue)
                    .foregroundStyle(active ? TUI.accent : TUI.dim)
                    .onTapGesture {
                        vm.librarySection = s; vm.openedPlaylist = nil; vm.highlightIndex = 0
                        if s == .ytm { vm.loadYTMLibrary() }
                    }
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
            .scrollDisabled(navMode || dragQueueIndex != nil)
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
        } else if vm.tab == .library && vm.librarySection == .ytm {
            ytmRows
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
        // Queue rows drag-reorder from either edge (left marker/number zone, right ≡ handle).
        let reorderable = (vm.tab == .queue && !r.isPlaylist)
        let dragged = reorderable && dragQueueIndex == idx
        return HStack(spacing: 8) {
            HStack(spacing: 8) {
                Text(playing ? "▸" : (r.isPlaylist ? "≡" : (highlighted ? "›" : " ")))
                    .foregroundStyle(TUI.accent)
                Text(String(format: "%2d", idx + 1)).foregroundStyle(TUI.dim)
            }
            .frame(height: rowHeight)
            .contentShape(Rectangle())
            .gesture(reorderDrag(idx), including: reorderable ? .all : .subviews)
            if playing {
                WaveText(text: r.title, palette: theme.current.wave, font: TUI.mono(13),
                         fallback: TUI.accent, active: playback.isPlaying, lineLimit: 1)
            } else {
                Text(r.title).foregroundStyle(TUI.fg).lineLimit(1).truncationMode(.tail)
            }
            Spacer(minLength: 6)
            Text(r.isPlaylist ? "playlist" : timeString(Double(r.duration)))
                .foregroundStyle(TUI.dim)
            if reorderable {
                Text("≡")
                    .foregroundStyle(dragged ? TUI.accent : TUI.dim)
                    .frame(width: 26, height: rowHeight)
                    .contentShape(Rectangle())
                    .gesture(reorderDrag(idx))
            }
        }
        .font(TUI.mono(13))
        .frame(height: rowHeight)
        .background(dragged ? TUI.accent.opacity(0.25)
                            : (highlighted ? TUI.accent.opacity(0.12) : .clear))
        .contentShape(Rectangle())
        .onTapGesture(count: 2) { vm.tab = (vm.tab == .search ? .queue : .search) }
        .onTapGesture { playRow(idx) }
    }

    private func playRow(_ idx: Int) {
        // A playlist/album row (e.g. in For You) opens to a view-first list rather than plays.
        if vm.displayed.indices.contains(idx), vm.displayed[idx].isPlaylist {
            let r = vm.displayed[idx]
            vm.openPlaylist(id: r.playlistId ?? r.id, title: r.title)
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

    // The signed-in account's real YouTube Music library (Library → yt music).
    @ViewBuilder private var ytmRows: some View {
        if !account.signedIn {
            Text("sign in (settings → account) to see your YouTube Music library")
                .foregroundStyle(TUI.dim).padding(.vertical, 8)
        } else {
            HStack(spacing: 8) {
                Text("♥").foregroundStyle(TUI.accent)
                Text("Your Likes").foregroundStyle(TUI.fg)
                Spacer(minLength: 6)
                if vm.ytmLibLoading { ProgressView().controlSize(.mini).tint(TUI.accent) }
            }
            .font(TUI.mono(13))
            .frame(height: rowHeight)
            .contentShape(Rectangle())
            .onTapGesture { vm.openPlaylist(id: "LM", title: "Your Likes") }

            if let e = vm.ytmLibError {
                Text("library error: \(e) — tap to retry")
                    .foregroundStyle(TUI.warn).font(TUI.mono(12))
                    .padding(.vertical, 6)
                    .contentShape(Rectangle())
                    .onTapGesture { vm.loadYTMLibrary(force: true) }
            }
            ForEach(vm.ytmPlaylists) { p in
                HStack(spacing: 8) {
                    Text("♫").foregroundStyle(TUI.accent)
                    Text(p.name).foregroundStyle(TUI.fg).lineLimit(1)
                    Spacer(minLength: 6)
                    if p.count > 0 {
                        Text("\(p.count)").foregroundStyle(TUI.dim)
                    }
                }
                .font(TUI.mono(13))
                .frame(height: rowHeight)
                .contentShape(Rectangle())
                .onTapGesture { vm.openPlaylist(id: p.playlistId, title: p.name) }
            }
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
                    Text("\(s.queue.count) tracks · \(timeString(s.position))"
                         + (s.device.map { " · \($0)" } ?? ""))
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
                    guard dragQueueIndex == nil else { return }   // a reorder drag owns the touch
                    navMode = true
                    if dragStartHighlight == nil { dragStartHighlight = vm.highlightIndex }
                    let delta = Int((drag.translation.height / rowHeight).rounded())
                    vm.highlightIndex = min(max((dragStartHighlight ?? 0) + delta, 0),
                                            max(vm.displayed.count - 1, 0))
                }
            }
            .onEnded { _ in dragStartHighlight = nil; navMode = false }
    }

    /// Queue drag-to-reorder: hold a row's left (marker/number) or right (≡ handle) edge
    /// ~0.2 s to pick the song up, then drag; the row moves live as you cross row
    /// boundaries. Global coordinate space — the dragged row itself moves, so its local
    /// space would shift under the gesture. Scrolling is suspended while active.
    private func reorderDrag(_ idx: Int) -> some Gesture {
        LongPressGesture(minimumDuration: 0.2)
            .sequenced(before: DragGesture(minimumDistance: 0, coordinateSpace: .global))
            .onChanged { value in
                guard case .second(true, let drag) = value else { return }
                if dragStartQueue == nil {
                    dragStartQueue = idx
                    dragQueueIndex = idx
                    UIImpactFeedbackGenerator(style: .medium).impactOccurred()
                }
                guard let d = drag, let start = dragStartQueue, let cur = dragQueueIndex
                else { return }
                let target = min(max(start + Int((d.translation.height / rowHeight).rounded()), 0),
                                 max(vm.queue.count - 1, 0))
                if target != cur {
                    withAnimation(.easeInOut(duration: 0.12)) {
                        vm.moveQueueItem(from: cur, to: target)
                    }
                    dragQueueIndex = target
                }
            }
            .onEnded { _ in dragStartQueue = nil; dragQueueIndex = nil }
    }

    // MARK: - Now playing

    /// The artist/uploader label under the title — tappable → that artist's page.
    @ViewBuilder private func artistLabel(font: Font) -> some View {
        let name = playback.current?.uploader ?? " "
        Text(name)
            .font(font).foregroundStyle(TUI.dim).lineLimit(1)
            .contentShape(Rectangle())
            .onTapGesture { if !name.trimmingCharacters(in: .whitespaces).isEmpty {
                vm.openArtistByName(name) } }
    }

    /// The launch-armed resume session, only while nothing is actually playing yet.
    private var armedResume: Session? {
        playback.current == nil ? vm.pendingResume : nil
    }

    private var nowPlaying: some View {
        VStack(spacing: 6) {
            HStack(spacing: 10) {
                HStack(spacing: 10) {
                    AsyncImage(url: playback.current?.thumbnailURL
                               ?? (armedResume != nil ? vm.currentResult?.thumbnailURL : nil)) { phase in
                        if case .success(let img) = phase { img.resizable().scaledToFill() }
                        else { TUI.panel }
                    }
                    .frame(width: 48, height: 48)
                    .clipShape(RoundedRectangle(cornerRadius: 4))
                    .contentShape(Rectangle())
                    .onTapGesture {
                        if playback.current != nil { showNowPlaying = true }   // expand
                        else if armedResume != nil { vm.resumePending() }
                    }
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: 6) {
                            PulseGlyph(glyphs: theme.current.glyphs,
                                       font: TUI.mono(13, .bold),
                                       active: playback.isPlaying && playback.current != nil)
                            WaveText(text: playback.current?.title
                                           ?? armedResume?.title ?? "nothing playing",
                                     palette: theme.current.wave,
                                     font: TUI.mono(14, .bold),
                                     fallback: TUI.fg,
                                     active: playback.isPlaying && playback.current != nil,
                                     lineLimit: 1)
                        }
                        .contentShape(Rectangle())
                        .onTapGesture {
                            if playback.current != nil { showNowPlaying = true }   // expand
                            else if armedResume != nil { vm.resumePending() }
                        }
                        if let s = armedResume {
                            Text("resume \u{25B8} at \(timeString(s.position))")
                                .font(TUI.mono(12)).foregroundStyle(TUI.accent)
                                .contentShape(Rectangle())
                                .onTapGesture { vm.resumePending() }
                        } else {
                            artistLabel(font: TUI.mono(12))   // tap → artist page
                        }
                    }
                    Spacer()
                }
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
                Button {
                    if armedResume != nil { vm.resumePending() }
                    else { playback.togglePlayPause() }
                } label: {
                    Image(systemName: playback.isPlaying ? "pause.fill" : "play.fill").font(.largeTitle)
                }
                Button { vm.playNext() } label: { Image(systemName: "forward.end.fill").font(.title2) }
            }
            .foregroundStyle(TUI.accent)
            .disabled(playback.current == nil && armedResume == nil)
            .padding(.top, 2)
        }
    }

    private var likedNow: Bool {
        guard let r = vm.currentResult else { return false }
        return library.isLiked(r.id)
    }

    // MARK: - Footer

    private func footer(showLyricsButton: Bool) -> some View {
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
            if showLyricsButton {
                sep
                Text("lyrics")
                    .foregroundStyle(showLyricsPanel ? TUI.accent : TUI.dim)
                    .onTapGesture { showLyricsPanel.toggle() }
            }
            Spacer()
            HStack(spacing: 3) {
                if updater.updateAvailable {
                    Text("↑").font(TUI.mono(11, .bold)).foregroundStyle(TUI.accent)
                }
                Image(systemName: "gearshape").foregroundStyle(TUI.dim)
            }
            .contentShape(Rectangle())
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
