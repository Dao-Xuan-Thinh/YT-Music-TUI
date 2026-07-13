import Combine
import Foundation

enum RepeatMode: String { case off, all }
enum SearchSource: String, CaseIterable { case ytm, yt, both }
enum Tab { case search, queue, library, foryou }
enum LibrarySection: String, CaseIterable { case liked, playlists, recent, resume }

/// Owns the search results AND the play queue (kept separate so searching never disturbs
/// what's currently playing). Search/resolution run off-main via the Python bridge.
@MainActor
final class PlayerViewModel: ObservableObject {
    @Published var results: [SearchResult] = []   // SEARCH tab (search/browse output)
    @Published var queue: [SearchResult] = []      // QUEUE tab (what's actually playing)
    @Published var queueIndex: Int?                // index into `queue`
    @Published var highlightIndex = 0              // gesture cursor in the displayed list
    @Published var shuffle = false
    @Published var repeatMode: RepeatMode = .off
    @Published var source: SearchSource = .ytm
    @Published var tab: Tab = .search
    @Published var librarySection: LibrarySection = .liked
    @Published var openedPlaylist: String?         // name of the playlist being viewed
    @Published var searching = false
    @Published var resolving = false
    @Published var errorMsg: String?
    @Published var home: [SearchResult] = []       // FOR YOU feed (anonymous home)
    @Published var homeLoading = false
    @Published var artistHit: ArtistHit?           // top artist card above search results
    @Published var artistPage: ArtistPage?         // loaded artist page (nil = not open)
    @Published var artistLoading = false
    @Published var openedCollection: Bool = false  // a playlist/album is open (view-first)
    @Published var collectionTitle = ""
    @Published var collectionTracks: [SearchResult] = []
    @Published var collectionLoading = false
    @Published var lyricLines: [LyricLine] = []    // current track's lyrics (empty = none)
    @Published var lyricsSynced = false
    @Published var lyricsSource = ""
    @Published var lyricsLoading = false
    @Published var lyricsAvailable = false
    // Translation (off until the user toggles it).
    @Published var translateOn = false
    @Published var translateLang = "en"
    @Published var lyricsTranslated: [String] = []  // aligned to lyricLines
    @Published var translating = false
    private var lyricsForID: String?
    private var lyricsFullText = ""

    let playback = PlaybackService.shared
    let library = LibraryStore.shared

    private var resolveToken = 0
    private var prefetched: [String: Track] = [:]
    private var resolveWorkItem: DispatchWorkItem?   // pending debounced resolve (cancellable)

    init() {
        source = AppConfig.shared.defaultSource
        playback.onEnded = { [weak self] in self?.playNext(auto: true) }
        playback.onNext = { [weak self] in self?.playNext() }
        playback.onPrevious = { [weak self] in self?.playPrevious() }
    }

    var playingID: String? { playback.current?.id }

    /// The track list under the gesture cursor. Library's `playlists`/`resume` sub-sections
    /// render their own row types (playlist names / sessions), so they have no track list here.
    var displayed: [SearchResult] {
        switch tab {
        case .search:  return results
        case .queue:   return queue
        case .foryou:  return home
        case .library:
            switch librarySection {
            case .liked:  return library.liked
            case .recent: return library.recent
            case .playlists:
                // When a playlist is opened, its tracks are the displayed list.
                if let n = openedPlaylist, let p = library.playlist(named: n) { return p.tracks }
                return []
            case .resume: return []
            }
        }
    }

    /// The lite row of whatever is playing now (the queue item at `queueIndex`).
    var currentResult: SearchResult? {
        guard let i = queueIndex, queue.indices.contains(i) else { return nil }
        return queue[i]
    }

    // MARK: - Search / browse (updates `results` only)

    func submit(_ query: String) {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { return }
        let isURL = q.hasPrefix("http://") || q.hasPrefix("https://")
        searching = true
        errorMsg = nil
        artistHit = nil
        artistPage = nil
        let src = source.rawValue
        DispatchQueue.global(qos: .userInitiated).async {
            let c = isURL ? python_browse(q) : python_search(q, src)
            let json = c.map { String(cString: $0) } ?? "[]"
            if let c { free(c) }
            let list = SearchResult.decodeList(json)
            DispatchQueue.main.async {
                self.searching = false
                self.results = list
                self.highlightIndex = 0
                if list.isEmpty {
                    self.errorMsg = "No results"
                    DebugLog.shared.log("search", "\(isURL ? "browse" : "search") returned nothing for \(q)")
                }
                else if isURL { self.playFromResults(at: 0) }   // paste-and-play url/playlist
            }
        }
        // In parallel, look up the top artist for a keyword query (not a URL) → card.
        if !isURL {
            DispatchQueue.global(qos: .utility).async {
                let c = python_search_artist(q)
                let json = c.map { String(cString: $0) } ?? "{}"
                if let c { free(c) }
                let hit = ArtistHit.decode(json)
                DispatchQueue.main.async { self.artistHit = hit }
            }
        }
    }

    func cycleSource() {
        let all = SearchSource.allCases
        source = all[(all.firstIndex(of: source)! + 1) % all.count]
    }

    /// Load the "For You" home feed (lazy: skipped if already loaded unless `force`).
    func loadHome(force: Bool = false) {
        guard force || home.isEmpty, !homeLoading else { return }
        homeLoading = true
        DispatchQueue.global(qos: .userInitiated).async {
            let c = python_home()
            let json = c.map { String(cString: $0) } ?? "[]"
            if let c { free(c) }
            let list = SearchResult.decodeList(json)
            DispatchQueue.main.async {
                self.homeLoading = false
                self.home = list
                if list.isEmpty { DebugLog.shared.log("home", "feed returned nothing") }
                self.backfillDurations(\.home)   // home API omits durations → fetch real ones
            }
        }
    }

    /// The home feed doesn't include song durations, so fetch the real values in one
    /// background batch and patch the rows (one UI update). Cap the batch to stay light.
    private func backfillDurations(_ keyPath: ReferenceWritableKeyPath<PlayerViewModel, [SearchResult]>) {
        let ids = self[keyPath: keyPath]
            .filter { $0.kind == "song" && $0.duration == 0 }
            .prefix(30).map { $0.id }
        guard !ids.isEmpty else { return }
        let csv = ids.joined(separator: ",")
        DispatchQueue.global(qos: .utility).async {
            let c = python_durations(csv)
            let json = c.map { String(cString: $0) } ?? "{}"
            if let c { free(c) }
            let map = (try? JSONDecoder().decode([String: Int].self, from: Data(json.utf8))) ?? [:]
            guard !map.isEmpty else { return }
            DispatchQueue.main.async {
                self[keyPath: keyPath] = self[keyPath: keyPath].map { r in
                    if r.duration == 0, let s = map[r.id] { return r.with(duration: s) }
                    return r
                }
            }
        }
    }

    // MARK: - Play

    /// Promote an arbitrary list to the active queue, then play `idx`. The shared entry
    /// point for SEARCH and every LIBRARY section.
    func playList(_ list: [SearchResult], at idx: Int) {
        guard list.indices.contains(idx) else { return }
        queue = list
        play(at: idx)
    }

    /// Play from the SEARCH list: promote `results` to the active queue, then play.
    func playFromResults(at idx: Int) { playList(results, at: idx) }

    /// Play from the QUEUE list (queue unchanged).
    func playFromQueue(at idx: Int) {
        guard queue.indices.contains(idx) else { return }
        play(at: idx)
    }

    private func play(at idx: Int, resumeAt: Double = 0) {
        // Invalidate any in-flight resolve up front — even when this selection is served from
        // the prefetch cache — so a slow earlier resolve can't complete and hijack playback.
        resolveToken &+= 1
        resolveWorkItem?.cancel()   // drop a pending (superseded) debounced resolve
        queueIndex = idx
        let r = queue[idx]
        library.addRecent(r)
        if let cached = prefetched[r.id] { startPlaying(cached, startAt: resumeAt); return }
        // Stop old audio immediately + show loading (no lingering while resolving).
        playback.beginLoading(title: r.title, uploader: r.uploader,
                              thumbnail: r.thumbnail, duration: r.duration)
        resolving = true
        errorMsg = nil
        // Debounce: a rapid re-selection (misclick) cancels this before it fires, so the
        // wrong song's extraction never starts (a started one can starve later resolves
        // under the GIL — the "stuck fetching forever" bug).
        let token = resolveToken
        let work = DispatchWorkItem { [weak self] in
            self?.resolveAndPlay(id: r.id, resumeAt: resumeAt, token: token)
        }
        resolveWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15, execute: work)
    }

    private func resolveAndPlay(id: String, resumeAt: Double = 0, token: Int) {
        // UI watchdog: if this resolve hasn't produced a result in time, stop showing the
        // spinner and offer a retry (the socket_timeout in resolve.py ends the work too).
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in
            guard let self, token == self.resolveToken, self.resolving else { return }
            self.resolving = false
            self.errorMsg = "Couldn't load this track — tap to try again."
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let c = python_resolve(id)
            let json = c.map { String(cString: $0) } ?? "{}"
            if let c { free(c) }
            let track = Track.decode(json)
            DispatchQueue.main.async {
                guard token == self.resolveToken else { return }  // a newer skip won
                self.resolving = false
                guard let t = track, t.ok, t.streamAVURL != nil else {
                    let msg = track?.error ?? "Could not resolve a playable stream"
                    DebugLog.shared.log("resolve", "\(id) failed: \(msg)")
                    self.errorMsg = msg; return
                }
                self.startPlaying(t, startAt: resumeAt)
            }
        }
    }

    private func startPlaying(_ track: Track, startAt: Double = 0) {
        prefetched[track.id] = track
        playback.play(track, startAt: startAt)
        prefetchNext()
    }

    /// Resolve the sequential next queue item in the background so advancing is gapless.
    private func prefetchNext() {
        guard !shuffle, let cur = queueIndex else { return }
        let next = cur + 1
        let target = next < queue.count ? next : (repeatMode == .all ? 0 : -1)
        guard queue.indices.contains(target) else { return }
        let id = queue[target].id
        guard prefetched[id] == nil else { return }
        DispatchQueue.global(qos: .utility).async {
            let c = python_resolve(id)
            let json = c.map { String(cString: $0) } ?? "{}"
            if let c { free(c) }
            if let t = Track.decode(json), t.ok, t.streamAVURL != nil {
                DispatchQueue.main.async { self.prefetched[t.id] = t }
            }
        }
    }

    // MARK: - Queue navigation

    func playNext(auto: Bool = false) {
        guard !queue.isEmpty, let cur = queueIndex else { return }
        if shuffle { play(at: queue.count == 1 ? cur : randomIndex(excluding: cur)); return }
        let next = cur + 1
        if next < queue.count { play(at: next) }
        else if repeatMode == .all { play(at: 0) }
    }

    func playPrevious() {
        guard !queue.isEmpty, let cur = queueIndex else { return }
        let prev = cur - 1
        play(at: prev >= 0 ? prev : (repeatMode == .all ? queue.count - 1 : 0))
    }

    private func randomIndex(excluding i: Int) -> Int {
        var n = i
        while n == i { n = Int.random(in: 0..<queue.count) }
        return n
    }

    // MARK: - Toggles & gesture cursor

    func toggleShuffle() { shuffle.toggle() }
    func cycleRepeat() { repeatMode = (repeatMode == .off) ? .all : .off }

    func moveHighlight(_ delta: Int) {
        let count = displayed.count
        guard count > 0 else { return }
        highlightIndex = min(max(highlightIndex + delta, 0), count - 1)
    }

    func playHighlighted() {
        guard displayed.indices.contains(highlightIndex) else { return }
        switch tab {
        case .search:           playFromResults(at: highlightIndex)
        case .queue:            playFromQueue(at: highlightIndex)
        case .library, .foryou: playList(displayed, at: highlightIndex)
        }
    }

    // MARK: - Library actions

    /// Toggle "liked" on the track that's playing now. Returns true if now liked.
    @discardableResult
    func toggleLikeCurrent() -> Bool {
        guard let r = currentResult else { return false }
        return library.toggleLike(r)
    }

    func likeHighlighted() {
        guard displayed.indices.contains(highlightIndex) else { return }
        library.toggleLike(displayed[highlightIndex])
    }

    /// Save the current queue under a name (create or overwrite).
    func saveQueueAsPlaylist(name: String) {
        guard !queue.isEmpty else { return }
        library.savePlaylist(name: name, tracks: queue)
    }

    /// Load a saved playlist into the queue and start it.
    func playPlaylist(_ p: Playlist) {
        guard !p.tracks.isEmpty else { return }
        tab = .queue
        playList(p.tracks, at: 0)
    }

    /// Start an endless mix (radio) seeded from the currently-playing track: replaces the
    /// queue with the mix and plays from the top.
    func startRadio() {
        guard let seed = currentResult?.id, !seed.isEmpty else {
            errorMsg = "Play a song first to start radio"; return
        }
        searching = true
        errorMsg = nil
        DispatchQueue.global(qos: .userInitiated).async {
            let c = python_radio(seed)
            let json = c.map { String(cString: $0) } ?? "[]"
            if let c { free(c) }
            let list = SearchResult.decodeList(json)
            DispatchQueue.main.async {
                self.searching = false
                guard !list.isEmpty else { self.errorMsg = "No radio for this track"; return }
                self.tab = .queue
                self.playList(list, at: 0)
            }
        }
    }

    /// Open the artist page for a channelId (from the artist card).
    func openArtist(_ hit: ArtistHit) {
        artistLoading = true
        artistPage = nil
        DispatchQueue.global(qos: .userInitiated).async {
            let c = python_artist(hit.channelId)
            let json = c.map { String(cString: $0) } ?? "{}"
            if let c { free(c) }
            let page = ArtistPage.decode(json)
            DispatchQueue.main.async {
                self.artistLoading = false
                self.artistPage = page ?? ArtistPage(name: hit.name, thumbnail: hit.thumbnail,
                                                     subscribers: "", sections: [])
            }
        }
    }

    func closeArtist() { artistPage = nil }

    /// Fetch lyrics for a videoId (once per id) → publishes structured lines + source.
    /// Resets any active translation (re-fetched on demand for the new track).
    func loadLyrics(for id: String) {
        guard !id.isEmpty, lyricsForID != id else { return }
        lyricsForID = id
        lyricLines = []
        lyricsTranslated = []
        lyricsSynced = false
        lyricsAvailable = false
        lyricsSource = ""
        lyricsFullText = ""
        lyricsLoading = true
        DispatchQueue.global(qos: .utility).async {
            let c = python_lyrics(id)
            let json = c.map { String(cString: $0) } ?? "{}"
            if let c { free(c) }
            let resp = LyricsResponse.decode(json)
            DispatchQueue.main.async {
                guard self.lyricsForID == id else { return }   // a newer track won
                self.lyricsLoading = false
                if let r = resp {
                    self.lyricLines = r.lines
                    self.lyricsSynced = r.synced
                    self.lyricsSource = r.source
                    self.lyricsFullText = r.text
                    self.lyricsAvailable = !r.lines.isEmpty
                    if self.translateOn { self.fetchTranslation() }   // keep translation on
                }
            }
        }
    }

    /// The index of the lyric line for the current playback position (synced only).
    func currentLyricIndex(positionSeconds: Double) -> Int {
        guard lyricsSynced else { return -1 }
        let ms = Int(positionSeconds * 1000)
        var cur = -1
        for (i, ln) in lyricLines.enumerated() {
            if ln.start <= ms { cur = i } else { break }
        }
        return cur
    }

    func toggleTranslate() {
        translateOn.toggle()
        if translateOn && lyricsTranslated.isEmpty { fetchTranslation() }
    }

    func setTranslateLang(_ code: String) {
        let c = code.trimmingCharacters(in: .whitespaces).lowercased()
        guard !c.isEmpty, c != translateLang else { return }
        translateLang = c
        lyricsTranslated = []
        if translateOn { fetchTranslation() }
    }

    private func fetchTranslation() {
        let text = lyricsFullText
        guard !text.isEmpty, !translating else { return }
        let lang = translateLang
        let id = lyricsForID
        translating = true
        DispatchQueue.global(qos: .utility).async {
            let c = python_translate(text, lang)
            let json = c.map { String(cString: $0) } ?? "{}"
            if let c { free(c) }
            let obj = (try? JSONSerialization.jsonObject(with: Data(json.utf8))) as? [String: Any]
            let ok = (obj?["ok"] as? Bool) ?? false
            let translated = (obj?["text"] as? String) ?? ""
            DispatchQueue.main.async {
                guard self.lyricsForID == id else { return }
                self.translating = false
                self.lyricsTranslated = ok ? translated.components(separatedBy: "\n") : []
            }
        }
    }

    /// Open the artist page for a plain artist name (from the now-playing artist label):
    /// look up the top artist match, then open it.
    func openArtistByName(_ name: String) {
        let n = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !n.isEmpty else { return }
        artistLoading = true
        DispatchQueue.global(qos: .userInitiated).async {
            let c = python_search_artist(n)
            let json = c.map { String(cString: $0) } ?? "{}"
            if let c { free(c) }
            let hit = ArtistHit.decode(json)
            DispatchQueue.main.async {
                self.artistLoading = false
                if let hit { self.openArtist(hit) }
            }
        }
    }

    // MARK: - View-first collections (playlists / albums)

    /// Open an album (browseId, from an artist album row) — view first, don't auto-play.
    func openAlbum(id: String, title: String) {
        loadCollection(title: title) { python_album(id) }
    }

    /// Open a YT-Music playlist by id (from a For-You playlist row) — view first.
    func openPlaylist(id: String, title: String) {
        let url = "https://music.youtube.com/playlist?list=\(id)"
        loadCollection(title: title) { python_browse(url) }
    }

    /// Shared loader: present the collection sheet with a spinner, fetch its tracks off-main,
    /// then fill them. Playing is explicit (`playCollection`).
    private func loadCollection(title: String, _ fetch: @escaping () -> UnsafeMutablePointer<CChar>?) {
        collectionTitle = title
        collectionTracks = []
        collectionLoading = true
        openedCollection = true
        DispatchQueue.global(qos: .userInitiated).async {
            let c = fetch()
            let json = c.map { String(cString: $0) } ?? "[]"
            if let c { free(c) }
            let list = SearchResult.decodeList(json)
            DispatchQueue.main.async {
                self.collectionLoading = false
                self.collectionTracks = list
            }
        }
    }

    func closeCollection() { openedCollection = false }

    /// Play the opened collection (optionally from a given index), closing the sheet.
    func playCollection(at idx: Int = 0) {
        guard !collectionTracks.isEmpty else { return }
        let tracks = collectionTracks
        openedCollection = false
        artistPage = nil
        tab = .queue
        playList(tracks, at: min(max(idx, 0), tracks.count - 1))
    }

    /// Restore a saved session: its queue, index, and playback position.
    func restore(_ s: Session) {
        guard s.queue.indices.contains(s.index) else { return }
        queue = s.queue
        tab = .queue
        play(at: s.index, resumeAt: s.position)
    }

    /// Snapshot the current queue + position as a resume session (called on backgrounding).
    func saveCurrentSession() {
        guard !queue.isEmpty, let i = queueIndex else { return }
        let title = queue.indices.contains(i) ? queue[i].title : "session"
        library.saveSession(queue: queue, index: i, position: playback.position, title: title)
    }
}
