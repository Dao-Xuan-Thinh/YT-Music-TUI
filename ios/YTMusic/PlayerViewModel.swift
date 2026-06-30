import Combine
import Foundation

enum RepeatMode: String { case off, all }
enum SearchSource: String, CaseIterable { case ytm, yt, both }
enum Tab { case search, queue, library }
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

    let playback = PlaybackService.shared
    let library = LibraryStore.shared

    private var resolveToken = 0
    private var prefetched: [String: Track] = [:]

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
                if list.isEmpty { self.errorMsg = "No results" }
                else if isURL { self.playFromResults(at: 0) }   // paste-and-play url/playlist
            }
        }
    }

    func cycleSource() {
        let all = SearchSource.allCases
        source = all[(all.firstIndex(of: source)! + 1) % all.count]
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
        queueIndex = idx
        let r = queue[idx]
        library.addRecent(r)
        if let cached = prefetched[r.id] { startPlaying(cached, startAt: resumeAt); return }
        // Stop old audio immediately + show loading (no lingering while resolving).
        playback.beginLoading(title: r.title, uploader: r.uploader,
                              thumbnail: r.thumbnail, duration: r.duration)
        resolveAndPlay(id: r.id, resumeAt: resumeAt)
    }

    private func resolveAndPlay(id: String, resumeAt: Double = 0) {
        resolveToken &+= 1
        let token = resolveToken
        resolving = true
        errorMsg = nil
        DispatchQueue.global(qos: .userInitiated).async {
            let c = python_resolve(id)
            let json = c.map { String(cString: $0) } ?? "{}"
            if let c { free(c) }
            let track = Track.decode(json)
            DispatchQueue.main.async {
                guard token == self.resolveToken else { return }  // a newer skip won
                self.resolving = false
                guard let t = track, t.ok, t.streamAVURL != nil else {
                    self.errorMsg = track?.error ?? "Could not resolve a playable stream"; return
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
        case .search:  playFromResults(at: highlightIndex)
        case .queue:   playFromQueue(at: highlightIndex)
        case .library: playList(displayed, at: highlightIndex)
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
