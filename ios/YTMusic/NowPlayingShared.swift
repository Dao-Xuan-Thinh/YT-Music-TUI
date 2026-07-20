import Foundation

/// Now-playing snapshot shared with the widget extension (compiled into BOTH
/// targets, like StatsModel). The app writes it on track/state changes; the
/// Now Playing widget renders it. Pure Foundation — no network in the widget,
/// which also can't fetch remote images, so the app caches a small JPEG of the
/// artwork alongside.
struct NowPlayingSnapshot: Codable {
    var title: String = ""
    var uploader: String = ""
    var isPlaying: Bool = false
    var updated: Date = .distantPast

    var hasTrack: Bool { !title.isEmpty }
}

enum NowPlayingShared {
    static func snapshotURL() -> URL {
        StatsShared.storeURL().deletingLastPathComponent()
            .appendingPathComponent("nowplaying.json")
    }

    static func thumbURL() -> URL {
        StatsShared.storeURL().deletingLastPathComponent()
            .appendingPathComponent("nowplaying-thumb.jpg")
    }

    static func load() -> NowPlayingSnapshot {
        guard let data = try? Data(contentsOf: snapshotURL()) else {
            return NowPlayingSnapshot()
        }
        let dec = JSONDecoder()
        dec.dateDecodingStrategy = .iso8601
        return (try? dec.decode(NowPlayingSnapshot.self, from: data))
            ?? NowPlayingSnapshot()
    }

    static func write(_ snap: NowPlayingSnapshot) {
        let enc = JSONEncoder()
        enc.dateEncodingStrategy = .iso8601
        if let data = try? enc.encode(snap) {
            try? data.write(to: snapshotURL(), options: .atomic)
        }
    }
}
