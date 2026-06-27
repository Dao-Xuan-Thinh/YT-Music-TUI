import Combine
import Foundation

enum RepeatMode: String { case off, all }
enum SearchSource: String, CaseIterable { case ytm, yt, both }
enum Tab { case search, queue }

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
    @Published var searching = false
    @Published var resolving = false
    @Published var errorMsg: String?

    let playback = PlaybackService.shared

    private var resolveToken = 0
    private var prefetched: [String: Track] = [:]

    init() {
        playback.onEnded = { [weak self] in self?.playNext(auto: true) }
        playback.onNext = { [weak self] in self?.playNext() }
        playback.onPrevious = { [weak self] in self?.playPrevious() }
    }

    var playingID: String? { playback.current?.id }
    var displayed: [SearchResult] { tab == .search ? results : queue }

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

    /// Play from the SEARCH list: promote `results` to the active queue, then play.
    func playFromResults(at idx: Int) {
        guard results.indices.contains(idx) else { return }
        queue = results
        play(at: idx)
    }

    /// Play from the QUEUE list (queue unchanged).
    func playFromQueue(at idx: Int) {
        guard queue.indices.contains(idx) else { return }
        play(at: idx)
    }

    private func play(at idx: Int) {
        queueIndex = idx
        let r = queue[idx]
        if let cached = prefetched[r.id] { startPlaying(cached); return }
        // Stop old audio immediately + show loading (no lingering while resolving).
        playback.beginLoading(title: r.title, uploader: r.uploader,
                              thumbnail: r.thumbnail, duration: r.duration)
        resolveAndPlay(id: r.id)
    }

    private func resolveAndPlay(id: String) {
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
                self.startPlaying(t)
            }
        }
    }

    private func startPlaying(_ track: Track) {
        prefetched[track.id] = track
        playback.play(track)
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
        tab == .search ? playFromResults(at: highlightIndex) : playFromQueue(at: highlightIndex)
    }
}
