import Foundation

/// The top artist match shown as a card above search results.
struct ArtistHit: Codable, Equatable {
    let name: String
    let channelId: String
    let thumbnail: String

    var thumbnailURL: URL? { thumbnail.isEmpty ? nil : URL(string: thumbnail) }

    /// Decode from `python_search_artist` JSON; nil when `{}` (no match).
    static func decode(_ json: String) -> ArtistHit? {
        guard let data = json.data(using: .utf8),
              let hit = try? JSONDecoder().decode(ArtistHit.self, from: data),
              !hit.channelId.isEmpty else { return nil }
        return hit
    }
}

/// One section on the artist page (Songs / Albums / Singles / Videos).
struct ArtistSection: Codable, Identifiable, Equatable {
    let title: String
    let kind: String
    let items: [SearchResult]
    var id: String { kind }
}

/// A full artist page from `python_artist`.
struct ArtistPage: Codable, Equatable {
    let name: String
    let thumbnail: String
    let subscribers: String
    let sections: [ArtistSection]

    var thumbnailURL: URL? { thumbnail.isEmpty ? nil : URL(string: thumbnail) }

    static func decode(_ json: String) -> ArtistPage? {
        guard let data = json.data(using: .utf8),
              let page = try? JSONDecoder().decode(ArtistPage.self, from: data),
              !page.name.isEmpty else { return nil }
        return page
    }
}
