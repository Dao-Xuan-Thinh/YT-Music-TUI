import Foundation
import SwiftUI
import UIKit

/// Listen-time data model + shared storage location. Pure Foundation on purpose:
/// this file is compiled into BOTH the app and the widget extension, and it is
/// the only source they share. The widget never talks to the network — it only
/// reads the JSON the app writes here.
struct DeviceStats: Codable {
    var device: String
    var days: [String: Double]   // "yyyy-MM-dd" (local time) → listened seconds
    // "yyyy-MM" → "<id>|<title>|<uploader>" → seconds (monthly top charts)
    var top: [String: [String: Double]]? = nil
}

struct StatsFile: Codable {
    var days: [String: Double] = [:]            // this install's own counters
    var top: [String: [String: Double]] = [:]   // own monthly attribution
    var remote: [String: DeviceStats] = [:]     // last gist pull, keyed by device id
    var lastSync: Date? = nil
    var deviceID: String? = nil                 // ours — lets the widget dedup exactly
}

// MARK: - Cross-device library sync (wire format shared with desktop stats.py)
//
// Each device's gist file carries a "library" blob: liked + playlists +
// newest sessions, with per-entry timestamps and deletion tombstones. The
// merge below MUST mirror desktop `library.merge_sync` exactly: newest ts
// wins; a removal beats an older add and loses ties to an add; tombstones
// expire after 90 days.

struct SyncTrack: Codable {
    var id: String
    var title: String
    var uploader: String
    var duration: Int
}

struct SyncLikedEntry: Codable {
    var t: SyncTrack
    var ts: Double
}

struct SyncPlaylist: Codable {
    var name: String
    var tracks: [SyncTrack]
    var ts: Double
}

struct SyncSession: Codable {
    var id: String
    var title: String
    var queue: [SyncTrack]
    var queueIdx: Int
    var position: Double
    var shuffle: Bool?
    var repeatMode: String?
    var ts: Double
    var device: String?

    enum CodingKeys: String, CodingKey {
        case id, title, queue, position, shuffle, ts, device
        case queueIdx = "queue_idx"
        case repeatMode = "repeat"
    }
}

struct LibraryBlob: Codable {
    var liked: [SyncLikedEntry] = []
    var likedRM: [String: Double] = [:]
    var playlists: [SyncPlaylist] = []
    var playlistsRM: [String: Double] = [:]
    var sessions: [SyncSession] = []
    var sessionsRM: [String: Double] = [:]

    enum CodingKeys: String, CodingKey {
        case liked, playlists, sessions
        case likedRM = "liked_rm"
        case playlistsRM = "playlists_rm"
        case sessionsRM = "sessions_rm"
    }
}

enum LibrarySync {
    static let tombstoneTTL: Double = 90 * 86400
    static let sessionCap = 10

    /// Merge every device's blob into one authoritative state (pure).
    static func merge(_ blobs: [LibraryBlob], now: Double = Date().timeIntervalSince1970) -> LibraryBlob {
        let cutoff = now - tombstoneTTL

        // liked: id -> (ts, track?) — adds use >=, removals use > (ties → liked)
        var liked: [String: (ts: Double, t: SyncTrack?)] = [:]
        for b in blobs {
            for e in b.liked where !e.t.id.isEmpty {
                if liked[e.t.id] == nil || e.ts >= liked[e.t.id]!.ts {
                    liked[e.t.id] = (e.ts, e.t)
                }
            }
            for (id, ts) in b.likedRM where ts >= cutoff {
                if liked[id] == nil || ts > liked[id]!.ts {
                    liked[id] = (ts, nil)
                }
            }
        }

        var pls: [String: (ts: Double, tracks: [SyncTrack]?)] = [:]
        for b in blobs {
            for p in b.playlists where !p.name.isEmpty {
                if pls[p.name] == nil || p.ts >= pls[p.name]!.ts {
                    pls[p.name] = (p.ts, p.tracks)
                }
            }
            for (name, ts) in b.playlistsRM where ts >= cutoff {
                if pls[name] == nil || ts > pls[name]!.ts {
                    pls[name] = (ts, nil)
                }
            }
        }

        var sess: [String: SyncSession] = [:]
        var sessRM: [String: Double] = [:]
        for b in blobs {
            for s in b.sessions where !s.id.isEmpty {
                if sess[s.id] == nil || s.ts > sess[s.id]!.ts { sess[s.id] = s }
            }
            for (id, ts) in b.sessionsRM where ts >= cutoff {
                sessRM[id] = max(ts, sessRM[id] ?? 0)
            }
        }
        for (id, ts) in sessRM where sess[id] != nil && ts >= sess[id]!.ts {
            sess[id] = nil
        }

        var out = LibraryBlob()
        out.liked = liked.compactMap { _, v in v.t.map { SyncLikedEntry(t: $0, ts: v.ts) } }
            .sorted { $0.ts > $1.ts }
        out.likedRM = liked.filter { $0.value.t == nil }.mapValues { $0.ts }
        out.playlists = pls.compactMap { name, v in
            v.tracks.map { SyncPlaylist(name: name, tracks: $0, ts: v.ts) }
        }.sorted { $0.name < $1.name }
        out.playlistsRM = pls.filter { $0.value.tracks == nil }.mapValues { $0.ts }
        out.sessions = Array(sess.values.sorted { $0.ts > $1.ts }.prefix(sessionCap))
        out.sessionsRM = sessRM
        return out
    }
}

enum StatsShared {
    static let appGroupID = "group.com.ytmtui.YTMusic"

    /// App Group container so the widget can read it. Falls back to Documents if
    /// the group isn't provisioned (free-team signing hiccup) — the app keeps
    /// tracking either way; the widget just shows its placeholder.
    static func storeURL() -> URL {
        if let c = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: appGroupID) {
            return c.appendingPathComponent("stats.json")
        }
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        return docs.appendingPathComponent("stats.json")
    }

    static func load() -> StatsFile {
        // MUST mirror StatsStore's encoder (.iso8601 dates): a mismatched date
        // strategy makes the whole decode fail the moment lastSync is set, which
        // read as "no data" — the widget showed its placeholder forever and the
        // app dropped its local counters at every relaunch.
        let dec = JSONDecoder()
        dec.dateDecodingStrategy = .iso8601
        guard let data = try? Data(contentsOf: storeURL()),
              let f = try? dec.decode(StatsFile.self, from: data)
        else { return StatsFile() }
        return f
    }

    static func dayKey(_ date: Date = Date()) -> String {
        let fmt = DateFormatter()
        fmt.locale = Locale(identifier: "en_US_POSIX")
        fmt.timeZone = .current
        fmt.dateFormat = "yyyy-MM-dd"
        return fmt.string(from: date)
    }

    /// The last n local dates, oldest first, ending today.
    static func lastDays(_ n: Int) -> [String] {
        let cal = Calendar.current
        return (0..<n).reversed().compactMap {
            cal.date(byAdding: .day, value: -$0, to: Date()).map(dayKey)
        }
    }

    /// day → total seconds across all devices. For our own device the value is
    /// max(local, remote copy) — the gist copy can be ahead of a wiped local
    /// store, but must never double-count.
    static func mergedDayMap(_ f: StatsFile) -> [String: Double] {
        var remote = f.remote
        let own = f.deviceID.flatMap { remote.removeValue(forKey: $0)?.days } ?? [:]
        var merged: [String: Double] = [:]
        for day in Set(f.days.keys).union(own.keys) {
            merged[day] = max(f.days[day] ?? 0, own[day] ?? 0)
        }
        for dev in remote.values {
            for (day, secs) in dev.days {
                merged[day, default: 0] += secs
            }
        }
        return merged
    }

    /// [(dayKey, seconds)] for the last n days, oldest first.
    static func mergedDays(_ f: StatsFile, last n: Int) -> [(String, Double)] {
        let map = mergedDayMap(f)
        return lastDays(n).map { ($0, map[$0] ?? 0) }
    }

    static func totals(_ f: StatsFile) -> (today: Double, week: Double, all: Double) {
        let map = mergedDayMap(f)
        let week = Set(lastDays(7))
        return (today: map[dayKey()] ?? 0,
                week: map.filter { week.contains($0.key) }.values.reduce(0, +),
                all: map.values.reduce(0, +))
    }

    /// Per-device lifetime totals, this device first. For our own device the
    /// per-day value is max(local, gist copy) — never double-counted; other
    /// devices come straight from their gist files.
    static func perDevice(_ f: StatsFile, ownName: String) -> [(name: String, secs: Double)] {
        var remote = f.remote
        let own = f.deviceID.flatMap { remote.removeValue(forKey: $0)?.days } ?? [:]
        let ownTotal = Set(f.days.keys).union(own.keys)
            .reduce(0.0) { $0 + max(f.days[$1] ?? 0, own[$1] ?? 0) }
        var out: [(name: String, secs: Double)] = [(ownName, ownTotal)]
        out += remote.values
            .map { ($0.device, $0.days.values.reduce(0, +)) }
            .sorted { $0.1 > $1.1 }
        return out
    }

    static func monthKey(_ date: Date = Date()) -> String {
        let fmt = DateFormatter()
        fmt.locale = Locale(identifier: "en_US_POSIX")
        fmt.timeZone = .current
        fmt.dateFormat = "yyyy-MM"
        return fmt.string(from: date)
    }

    /// One month's attribution map merged across devices (own copy max-deduped,
    /// others summed — same rule as the day counters).
    static func mergedTop(_ f: StatsFile, month: String) -> [String: Double] {
        var remote = f.remote.mapValues { ($0.top ?? [:])[month] ?? [:] }
        let own = f.deviceID.flatMap { remote.removeValue(forKey: $0) } ?? [:]
        let local = f.top[month] ?? [:]
        var merged: [String: Double] = [:]
        for k in Set(local.keys).union(own.keys) {
            merged[k] = max(local[k] ?? 0, own[k] ?? 0)
        }
        for dev in remote.values {
            for (k, secs) in dev { merged[k, default: 0] += secs }
        }
        return merged
    }

    /// Attribution merged across ALL retained months and devices (own copy
    /// max-deduped across its months, other devices summed). "All time" is
    /// practically the retained ~12-month window (older months are pruned).
    static func mergedTopAll(_ f: StatsFile) -> [String: Double] {
        func flatten(_ months: [String: [String: Double]]?) -> [String: Double] {
            var agg: [String: Double] = [:]
            for mv in (months ?? [:]).values {
                for (k, v) in mv { agg[k, default: 0] += v }
            }
            return agg
        }
        var remote = f.remote.mapValues { flatten($0.top) }
        let own = f.deviceID.flatMap { remote.removeValue(forKey: $0) } ?? [:]
        let local = flatten(f.top)
        var merged: [String: Double] = [:]
        for k in Set(local.keys).union(own.keys) {
            merged[k] = max(local[k] ?? 0, own[k] ?? 0)
        }
        for dev in remote.values {
            for (k, secs) in dev { merged[k, default: 0] += secs }
        }
        return merged
    }

    /// [(title, artist, seconds)] — most-listened tracks (this month or all time).
    static func topTracks(_ f: StatsFile, n: Int = 5,
                          allTime: Bool = false) -> [(String, String, Double)] {
        let map = allTime ? mergedTopAll(f) : mergedTop(f, month: monthKey())
        return map.sorted { $0.value > $1.value }.prefix(n)
            .map { key, secs in
                let parts = key.split(separator: "|", maxSplits: 2,
                                      omittingEmptySubsequences: false)
                return (parts.count > 1 ? String(parts[1]) : key,
                        parts.count > 2 ? String(parts[2]) : "", secs)
            }
    }

    /// [(artist, seconds)] — most-listened artists (this month or all time).
    static func topArtists(_ f: StatsFile, n: Int = 5,
                           allTime: Bool = false) -> [(String, Double)] {
        let map = allTime ? mergedTopAll(f) : mergedTop(f, month: monthKey())
        var agg: [String: Double] = [:]
        for (key, secs) in map {
            let parts = key.split(separator: "|", maxSplits: 2,
                                  omittingEmptySubsequences: false)
            let artist = parts.count > 2 ? String(parts[2]) : ""
            if !artist.isEmpty { agg[artist, default: 0] += secs }
        }
        return agg.sorted { $0.value > $1.value }.prefix(n).map { ($0.key, $0.value) }
    }

    // ── Derived day-based stats (from the never-pruned day counters) ─────────

    static let weekdayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    private static func parseDay(_ key: String) -> Date? {
        let fmt = DateFormatter()
        fmt.locale = Locale(identifier: "en_US_POSIX")
        fmt.timeZone = .current
        fmt.dateFormat = "yyyy-MM-dd"
        return fmt.date(from: key)
    }

    /// (current, longest) run of consecutive days with any listening.
    static func streak(_ f: StatsFile) -> (current: Int, longest: Int) {
        let days = Set(mergedDayMap(f).filter { $0.value > 0 }.keys)
        guard !days.isEmpty else { return (0, 0) }
        let cal = Calendar.current
        let parsed = days.compactMap(parseDay).map { cal.startOfDay(for: $0) }.sorted()
        var longest = 1, cur = 1
        for i in 1..<max(parsed.count, 1) where parsed.count > 1 {
            let gap = cal.dateComponents([.day], from: parsed[i-1], to: parsed[i]).day ?? 0
            cur = gap == 1 ? cur + 1 : 1
            longest = max(longest, cur)
        }
        // current run ending today or yesterday
        var current = 0
        var d = cal.startOfDay(for: Date())
        if !days.contains(dayKey(d)) {
            d = cal.date(byAdding: .day, value: -1, to: d)!
        }
        while days.contains(dayKey(d)) {
            current += 1
            d = cal.date(byAdding: .day, value: -1, to: d)!
        }
        return (current, longest)
    }

    /// (dayKey, seconds) of the single biggest listening day.
    static func bestDay(_ f: StatsFile) -> (day: String, secs: Double) {
        guard let best = mergedDayMap(f).max(by: { $0.value < $1.value }) else {
            return ("", 0)
        }
        return (best.key, best.value)
    }

    static func yearTotal(_ f: StatsFile) -> Double {
        let yr = String(dayKey().prefix(4))
        return mergedDayMap(f).filter { $0.key.hasPrefix(yr) }.values.reduce(0, +)
    }

    /// [seconds]*7, Monday..Sunday.
    static func weekdayTotals(_ f: StatsFile) -> [Double] {
        var out = [Double](repeating: 0, count: 7)
        let cal = Calendar.current
        for (key, secs) in mergedDayMap(f) {
            guard let d = parseDay(key) else { continue }
            // Calendar weekday: 1=Sun..7=Sat → index 0=Mon..6=Sun
            let idx = (cal.component(.weekday, from: d) + 5) % 7
            out[idx] += secs
        }
        return out
    }

    /// 132 → "2m", 9876 → "2h 44m".
    static func fmtMins(_ seconds: Double) -> String {
        let mins = Int(seconds / 60)
        return mins < 60 ? "\(mins)m"
                         : "\(mins / 60)h \(String(format: "%02d", mins % 60))m"
    }

    static func themeURL() -> URL {
        storeURL().deletingLastPathComponent().appendingPathComponent("widget-theme.json")
    }
}

/// The active app theme's colors, published into the App Group so the widget
/// matches the app instead of a hardcoded look. RGBA arrays because Color
/// isn't Codable. Written by ThemeManager on every theme change.
struct WidgetTheme: Codable {
    var bg: [Double]
    var panel: [Double]
    var fg: [Double]
    var dim: [Double]
    var accent: [Double]
    var dark: Bool

    static func rgba(_ c: Color) -> [Double] {
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        UIColor(c).getRed(&r, green: &g, blue: &b, alpha: &a)
        return [Double(r), Double(g), Double(b), Double(a)]
    }

    static func color(_ v: [Double]) -> Color {
        guard v.count == 4 else { return .gray }
        return Color(red: v[0], green: v[1], blue: v[2]).opacity(v[3])
    }

    static func load() -> WidgetTheme? {
        guard let data = try? Data(contentsOf: StatsShared.themeURL()),
              let t = try? JSONDecoder().decode(WidgetTheme.self, from: data)
        else { return nil }
        return t
    }

    func write() {
        if let data = try? JSONEncoder().encode(self) {
            try? data.write(to: StatsShared.themeURL(), options: .atomic)
        }
    }
}
