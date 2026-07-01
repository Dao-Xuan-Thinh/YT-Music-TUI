import Foundation

/// One resolved track. Mirrors the desktop track shape (`youtube._entry_to_dict`) and the
/// JSON returned by `python_resolve` (`ios/app/resolve.py`), so library JSON stays portable.
struct Track: Codable, Identifiable, Equatable {
    let id: String
    let title: String
    let uploader: String
    let duration: Int
    let url: String            // canonical https://www.youtube.com/watch?v=<id>
    let streamURL: String      // direct m4a stream for AVPlayer
    let thumbnail: String
    let ok: Bool
    let error: String?

    enum CodingKeys: String, CodingKey {
        case id, title, uploader, duration, url, thumbnail
        case streamURL = "stream_url"
        case ok = "_ok"
        case error = "_error"
    }

    var streamAVURL: URL? { URL(string: streamURL) }
    var thumbnailURL: URL? { thumbnail.isEmpty ? nil : URL(string: thumbnail) }

    /// Decode a Track from the resolver's JSON string.
    static func decode(_ json: String) -> Track? {
        guard let data = json.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(Track.self, from: data)
    }
}

/// A lite search-result row (no resolved stream yet — resolved on tap). `kind` distinguishes
/// a playable song from a playlist/album that opens; `playlistId` is set for the latter.
struct SearchResult: Codable, Identifiable, Equatable {
    let id: String
    let title: String
    let uploader: String
    let duration: Int
    let thumbnail: String
    var kind: String = "song"
    var playlistId: String? = nil

    var isPlaylist: Bool { kind == "playlist" }
    var thumbnailURL: URL? { thumbnail.isEmpty ? nil : URL(string: thumbnail) }

    /// Decode a `[SearchResult]` from the search JSON string (empty on failure).
    static func decodeList(_ json: String) -> [SearchResult] {
        guard let data = json.data(using: .utf8) else { return [] }
        return (try? JSONDecoder().decode([SearchResult].self, from: data)) ?? []
    }
}
