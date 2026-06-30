import Combine
import Foundation

/// A saved playlist — mirrors the desktop `library.py` `{'name', 'tracks'}` shape.
struct Playlist: Codable, Identifiable, Equatable {
    var name: String
    var tracks: [SearchResult]
    var id: String { name }
}

/// A saved playback session for Resume — the queue + where we were in it.
struct Session: Codable, Identifiable, Equatable {
    let id: UUID
    let savedAt: Date
    let title: String          // label = the track that was playing
    let queue: [SearchResult]
    let index: Int             // position within `queue`
    let position: Double       // seconds into the track
}

/// Persistent user library (liked / playlists / recent) + resume sessions, reimplemented in
/// Swift (no Python bridge) and saved to the app's Documents dir. Field names mirror the
/// desktop `library.py` JSON (`liked`/`playlists`/`recent`/`sessions`) so the data stays
/// recognizable across platforms. Tracks are stored as lite `SearchResult` rows; `id`
/// (videoId) is the key everywhere, matching the desktop's id-first `_track_key`.
@MainActor
final class LibraryStore: ObservableObject {
    static let shared = LibraryStore()

    @Published private(set) var liked: [SearchResult] = []
    @Published private(set) var playlists: [Playlist] = []
    @Published private(set) var recent: [SearchResult] = []
    @Published private(set) var sessions: [Session] = []

    private let recentCap = 100
    private let sessionCap = 10

    private let libURL: URL
    private let sessionsURL: URL

    /// `library.json` keeps liked/playlists/recent together (desktop shape).
    private struct LibraryFile: Codable {
        var liked: [SearchResult] = []
        var playlists: [Playlist] = []
        var recent: [SearchResult] = []
    }
    private struct SessionsFile: Codable {
        var sessions: [Session] = []
    }

    private init() {
        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        libURL = dir.appendingPathComponent("library.json")
        sessionsURL = dir.appendingPathComponent("sessions.json")
        load()
    }

    // MARK: - Load / save

    private func load() {
        if let data = try? Data(contentsOf: libURL),
           let f = try? JSONDecoder().decode(LibraryFile.self, from: data) {
            liked = f.liked; playlists = f.playlists; recent = f.recent
        }
        if let data = try? Data(contentsOf: sessionsURL),
           let f = try? JSONDecoder().decode(SessionsFile.self, from: data) {
            sessions = f.sessions
        }
    }

    private func saveLibrary() {
        write(LibraryFile(liked: liked, playlists: playlists, recent: recent), to: libURL)
    }
    private func saveSessions() {
        write(SessionsFile(sessions: sessions), to: sessionsURL)
    }
    private func write<T: Encodable>(_ value: T, to url: URL) {
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        if let data = try? enc.encode(value) {
            try? data.write(to: url, options: .atomic)
        }
    }

    // MARK: - Liked

    func isLiked(_ id: String) -> Bool { liked.contains { $0.id == id } }

    /// Toggle a track's liked state. Returns true if it is now liked.
    @discardableResult
    func toggleLike(_ r: SearchResult) -> Bool {
        guard !r.id.isEmpty else { return false }
        if let i = liked.firstIndex(where: { $0.id == r.id }) {
            liked.remove(at: i); saveLibrary(); return false
        }
        liked.insert(r, at: 0); saveLibrary(); return true
    }

    // MARK: - Recent

    func addRecent(_ r: SearchResult) {
        guard !r.id.isEmpty else { return }
        recent.removeAll { $0.id == r.id }
        recent.insert(r, at: 0)
        if recent.count > recentCap { recent.removeLast(recent.count - recentCap) }
        saveLibrary()
    }

    func removeRecent(_ id: String) {
        let before = recent.count
        recent.removeAll { $0.id == id }
        if recent.count != before { saveLibrary() }
    }

    func clearRecent() {
        if !recent.isEmpty { recent.removeAll(); saveLibrary() }
    }

    // MARK: - Playlists

    func playlist(named name: String) -> Playlist? { playlists.first { $0.name == name } }

    /// Create or overwrite a named playlist.
    func savePlaylist(name: String, tracks: [SearchResult]) {
        let n = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !n.isEmpty else { return }
        playlists.removeAll { $0.name == n }
        playlists.append(Playlist(name: n, tracks: tracks))
        saveLibrary()
    }

    func deletePlaylist(name: String) {
        playlists.removeAll { $0.name == name }
        saveLibrary()
    }

    /// Rename a saved playlist. Returns true on success (target name free + source exists).
    @discardableResult
    func renamePlaylist(old: String, new: String) -> Bool {
        let n = new.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !n.isEmpty, !playlists.contains(where: { $0.name == n }),
              let i = playlists.firstIndex(where: { $0.name == old }) else { return false }
        playlists[i].name = n
        saveLibrary()
        return true
    }

    // MARK: - Sessions (resume)

    func saveSession(queue: [SearchResult], index: Int, position: Double, title: String) {
        guard !queue.isEmpty else { return }
        let sig = queue.map(\.id)
        // Collapse repeated saves of the same queue (iOS backgrounds often) into one updated
        // entry rather than spamming near-duplicates up to the cap.
        if let first = sessions.first, first.queue.map(\.id) == sig {
            sessions[0] = Session(id: first.id, savedAt: Date(), title: title,
                                  queue: queue, index: index, position: position)
        } else {
            sessions.insert(Session(id: UUID(), savedAt: Date(), title: title,
                                    queue: queue, index: index, position: position), at: 0)
            if sessions.count > sessionCap { sessions.removeLast(sessions.count - sessionCap) }
        }
        saveSessions()
    }

    func deleteSession(id: UUID) {
        sessions.removeAll { $0.id == id }
        saveSessions()
    }
}
