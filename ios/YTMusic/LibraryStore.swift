import Combine
import Foundation

/// A saved playlist — mirrors the desktop `library.py` `{'name', 'tracks'}` shape.
struct Playlist: Codable, Identifiable, Equatable {
    var name: String
    var tracks: [SearchResult]
    var ts: Double? = nil      // last-edit time (cross-device sync merge key)
    var id: String { name }
}

/// A saved playback session for Resume — the queue + where we were in it.
/// `id` is a String (was UUID — old files decode unchanged since UUIDs encode
/// as strings) so desktop session ids sync in as-is; `device` labels sessions
/// that arrived from another device.
struct Session: Codable, Identifiable, Equatable {
    let id: String
    let savedAt: Date
    let title: String          // label = the track that was playing
    let queue: [SearchResult]
    let index: Int             // position within `queue`
    let position: Double       // seconds into the track
    var device: String? = nil
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
        // Cross-device sync bookkeeping (desktop library.py mirrors these).
        var likedTS: [String: Double]? = nil
        var tombLiked: [String: Double]? = nil
        var tombPlaylists: [String: Double]? = nil
        var tombSessions: [String: Double]? = nil
    }
    private struct SessionsFile: Codable {
        var sessions: [Session] = []
    }

    // Sync bookkeeping (persisted in LibraryFile).
    private(set) var likedTS: [String: Double] = [:]
    private var tombLiked: [String: Double] = [:]
    private var tombPlaylists: [String: Double] = [:]
    private var tombSessions: [String: Double] = [:]

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
            likedTS = f.likedTS ?? [:]
            tombLiked = f.tombLiked ?? [:]
            tombPlaylists = f.tombPlaylists ?? [:]
            tombSessions = f.tombSessions ?? [:]
        }
        if let data = try? Data(contentsOf: sessionsURL),
           let f = try? JSONDecoder().decode(SessionsFile.self, from: data) {
            sessions = f.sessions
        }
    }

    private func saveLibrary() {
        write(LibraryFile(liked: liked, playlists: playlists, recent: recent,
                          likedTS: likedTS, tombLiked: tombLiked,
                          tombPlaylists: tombPlaylists,
                          tombSessions: tombSessions), to: libURL)
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
        let now = Date().timeIntervalSince1970
        if let i = liked.firstIndex(where: { $0.id == r.id }) {
            liked.remove(at: i)
            likedTS[r.id] = nil
            tombLiked[r.id] = now
            saveLibrary()
            return false
        }
        liked.insert(r, at: 0)
        likedTS[r.id] = now
        tombLiked[r.id] = nil
        saveLibrary()
        return true
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

    /// Self-healing library: a YT Music upload died (removed/blocked) and playback
    /// found a living replacement by search — rewrite every stored reference so
    /// liked/playlists/recents don't keep pointing at the corpse.
    func replaceTrack(deadID: String, with sub: SearchResult) {
        guard !deadID.isEmpty, !sub.id.isEmpty, deadID != sub.id else { return }
        var changed = false
        func swapIn(_ list: inout [SearchResult]) {
            for i in list.indices where list[i].id == deadID {
                list[i] = sub
                changed = true
            }
        }
        swapIn(&liked)
        swapIn(&recent)
        for p in playlists.indices {
            for i in playlists[p].tracks.indices where playlists[p].tracks[i].id == deadID {
                playlists[p].tracks[i] = sub
                changed = true
            }
        }
        if changed { saveLibrary() }
    }

    func clearRecent() {
        if !recent.isEmpty { recent.removeAll(); saveLibrary() }
    }

    func clearLiked() {
        if !liked.isEmpty { liked.removeAll(); saveLibrary() }
    }

    func clearPlaylists() {
        if !playlists.isEmpty { playlists.removeAll(); saveLibrary() }
    }

    func clearSessions() {
        if !sessions.isEmpty { sessions.removeAll(); saveSessions() }
    }

    // MARK: - Playlists

    func playlist(named name: String) -> Playlist? { playlists.first { $0.name == name } }

    /// Create or overwrite a named playlist.
    func savePlaylist(name: String, tracks: [SearchResult]) {
        let n = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !n.isEmpty else { return }
        playlists.removeAll { $0.name == n }
        playlists.append(Playlist(name: n, tracks: tracks,
                                  ts: Date().timeIntervalSince1970))
        tombPlaylists[n] = nil
        saveLibrary()
    }

    func deletePlaylist(name: String) {
        playlists.removeAll { $0.name == name }
        tombPlaylists[name] = Date().timeIntervalSince1970
        saveLibrary()
    }

    /// Rename a saved playlist. Returns true on success (target name free + source exists).
    @discardableResult
    func renamePlaylist(old: String, new: String) -> Bool {
        let n = new.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !n.isEmpty, !playlists.contains(where: { $0.name == n }),
              let i = playlists.firstIndex(where: { $0.name == old }) else { return false }
        playlists[i].name = n
        playlists[i].ts = Date().timeIntervalSince1970
        tombPlaylists[old] = Date().timeIntervalSince1970
        tombPlaylists[n] = nil
        saveLibrary()
        return true
    }

    // MARK: - Sessions (resume)

    func saveSession(queue: [SearchResult], index: Int, position: Double, title: String) {
        guard !queue.isEmpty else { return }
        let sig = queue.map(\.id)
        // Collapse repeated saves of the same queue (iOS backgrounds often) into one updated
        // entry rather than spamming near-duplicates up to the cap.
        if let first = sessions.first, first.queue.map(\.id) == sig,
           first.device == nil {
            sessions[0] = Session(id: first.id, savedAt: Date(), title: title,
                                  queue: queue, index: index, position: position)
        } else {
            sessions.insert(Session(id: UUID().uuidString, savedAt: Date(),
                                    title: title, queue: queue, index: index,
                                    position: position), at: 0)
            if sessions.count > sessionCap { sessions.removeLast(sessions.count - sessionCap) }
        }
        saveSessions()
    }

    func deleteSession(id: String) {
        sessions.removeAll { $0.id == id }
        tombSessions[id] = Date().timeIntervalSince1970
        saveLibrary()
        saveSessions()
    }

    // MARK: - Cross-device sync (wire format + merge in StatsModel.swift)

    private func syncTrack(_ r: SearchResult) -> SyncTrack {
        SyncTrack(id: r.id, title: r.title, uploader: r.uploader,
                  duration: r.duration)
    }

    private func fromSync(_ t: SyncTrack) -> SearchResult {
        SearchResult(id: t.id, title: t.title, uploader: t.uploader,
                     duration: t.duration,
                     thumbnail: "https://i.ytimg.com/vi/\(t.id)/hqdefault.jpg")
    }

    /// This device's library as a sync blob (rides in our gist file).
    func exportSync(deviceName: String) -> LibraryBlob {
        var blob = LibraryBlob()
        blob.liked = liked.filter { !$0.isPlaylist }.map {
            SyncLikedEntry(t: syncTrack($0), ts: likedTS[$0.id] ?? 0)
        }
        blob.likedRM = tombLiked
        blob.playlists = playlists.map {
            SyncPlaylist(name: $0.name,
                         tracks: $0.tracks.prefix(200).map(syncTrack),
                         ts: $0.ts ?? 0)
        }
        blob.playlistsRM = tombPlaylists
        blob.sessions = sessions.prefix(5).compactMap { s in
            guard !s.queue.isEmpty else { return nil }
            return SyncSession(
                id: s.id, title: s.title,
                queue: s.queue.prefix(200).map(syncTrack),
                queueIdx: min(s.index, s.queue.count - 1),
                position: s.position, shuffle: false, repeatMode: "off",
                ts: s.savedAt.timeIntervalSince1970,
                device: s.device ?? deviceName)
        }
        blob.sessionsRM = tombSessions
        return blob
    }

    /// Apply a merged blob. Local rows are kept when present (they carry real
    /// thumbnails); merged-only entries are rebuilt from their lite form.
    /// Returns true if anything visible changed.
    @discardableResult
    func applySync(_ merged: LibraryBlob) -> Bool {
        let before = fingerprint()

        let localLiked = Dictionary(uniqueKeysWithValues: liked.map { ($0.id, $0) })
        liked = merged.liked.map { localLiked[$0.t.id] ?? fromSync($0.t) }
        likedTS = Dictionary(uniqueKeysWithValues: merged.liked.map { ($0.t.id, $0.ts) })

        let localPls = Dictionary(uniqueKeysWithValues: playlists.map { ($0.name, $0) })
        var newPls: [Playlist] = []
        for p in merged.playlists {
            if let loc = localPls[p.name], (loc.ts ?? 0) >= p.ts {
                newPls.append(loc)
            } else {
                newPls.append(Playlist(name: p.name,
                                       tracks: p.tracks.map(fromSync), ts: p.ts))
            }
        }
        // A local playlist the merge didn't mention is only dropped by tombstone.
        let mergedNames = Set(merged.playlists.map(\.name))
        for (name, p) in localPls
        where !mergedNames.contains(name) && merged.playlistsRM[name] == nil {
            newPls.append(p)
        }
        playlists = newPls.sorted { ($0.ts ?? 0) > ($1.ts ?? 0) }

        let localSess = Dictionary(uniqueKeysWithValues: sessions.map { ($0.id, $0) })
        var newSess: [Session] = []
        for s in merged.sessions {
            if let loc = localSess[s.id] {
                newSess.append(loc)
            } else {
                newSess.append(Session(
                    id: s.id, savedAt: Date(timeIntervalSince1970: s.ts),
                    title: s.title, queue: s.queue.map(fromSync),
                    index: min(max(0, s.queueIdx), max(0, s.queue.count - 1)),
                    position: s.position, device: s.device))
            }
        }
        let mergedIDs = Set(merged.sessions.map(\.id))
        for (id, s) in localSess
        where !mergedIDs.contains(id) && merged.sessionsRM[id] == nil {
            newSess.append(s)
        }
        sessions = Array(newSess.sorted { $0.savedAt > $1.savedAt }.prefix(sessionCap))

        tombLiked = merged.likedRM
        tombPlaylists = merged.playlistsRM
        tombSessions = merged.sessionsRM

        let changed = fingerprint() != before
        if changed {
            saveLibrary()
            saveSessions()
        }
        return changed
    }

    private func fingerprint() -> String {
        let l = liked.map { "\($0.id):\(likedTS[$0.id] ?? 0)" }.sorted().joined()
        let p = playlists.map { "\($0.name):\($0.ts ?? 0)" }.sorted().joined()
        let s = sessions.map(\.id).sorted().joined()
        return l + "|" + p + "|" + s
    }
}
