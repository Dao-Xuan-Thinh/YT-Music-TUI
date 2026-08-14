import Foundation
import SwiftUI
import UIKit

/// Listen-time data model + shared storage location. Pure Foundation on purpose:
/// this file is compiled into BOTH the app and the widget extension, and it is
/// the only source they share. The widget never talks to the network — it only
/// reads the JSON the app writes here.
/// One all-time counter: seconds listened, play count, first and last listen
/// (epoch seconds). Wire-identical to the desktop's dicts in `stats.py`, which is
/// why the keys are terse — these maps are the bulk of the synced file.
struct StatRecord: Codable, Equatable {
    var s: Double = 0     // seconds listened
    var n: Int = 0        // plays (a play counts once past min(30s, half the track))
    var f: Double = 0     // first listened, epoch seconds
    var l: Double = 0     // last listened, epoch seconds

    init(s: Double = 0, n: Int = 0, f: Double = 0, l: Double = 0) {
        self.s = s; self.n = n; self.f = f; self.l = l
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        s = (try? c.decodeIfPresent(Double.self, forKey: .s)) as? Double ?? 0
        n = (try? c.decodeIfPresent(Int.self, forKey: .n)) as? Int ?? 0
        f = (try? c.decodeIfPresent(Double.self, forKey: .f)) as? Double ?? 0
        l = (try? c.decodeIfPresent(Double.self, forKey: .l)) as? Double ?? 0
    }

    /// Same device seen twice (local vs its own gist copy): take the ahead-most
    /// value per field rather than adding, so a re-pull can never double-count.
    func maxed(_ o: StatRecord) -> StatRecord {
        StatRecord(s: Swift.max(s, o.s), n: Swift.max(n, o.n),
                   f: nonZeroMin(f, o.f), l: Swift.max(l, o.l))
    }

    /// Different devices: real independent listening, so add.
    func added(_ o: StatRecord) -> StatRecord {
        StatRecord(s: s + o.s, n: n + o.n,
                   f: nonZeroMin(f, o.f), l: Swift.max(l, o.l))
    }

    private func nonZeroMin(_ a: Double, _ b: Double) -> Double {
        if a == 0 { return b }
        if b == 0 { return a }
        return Swift.min(a, b)
    }
}

typealias StatRecords = [String: StatRecord]

struct DeviceStats: Codable {
    var device: String
    var days: [String: Double]   // "yyyy-MM-dd" (local time) → listened seconds
    // "yyyy-MM" → "<id>|<title>|<uploader>" → seconds (monthly top charts)
    var top: [String: [String: Double]]? = nil
    // All-time counters (added in 1.14; absent on files written by older clients).
    var artists: StatRecords? = nil        // artist name → record
    var tracks: StatRecords? = nil         // "<id>|<title>|<uploader>" → record
    var albums: StatRecords? = nil         // "<album>|<artist>" → record
    var clock: [String: Double]? = nil     // "<weekday 0=Mon>-<hour>" → seconds
}

struct StatsFile: Codable {
    var days: [String: Double] = [:]            // this install's own counters
    var top: [String: [String: Double]] = [:]   // own monthly attribution
    var remote: [String: DeviceStats] = [:]     // last gist pull, keyed by device id
    var lastSync: Date? = nil
    var deviceID: String? = nil                 // ours — lets the widget dedup exactly
    var artists: StatRecords = [:]              // all-time, never pruned
    var tracks: StatRecords = [:]               // all-time, capped at flush
    var albums: StatRecords = [:]               // all-time, fills from 1.14 onward
    var clock: [String: Double] = [:]           // weekday×hour heatmap buckets
    var seeded = false                          // one-time backfill from `top` has run

    init() {}

    /// Hand-written so a file missing ANY key still loads. `StatsShared.load()`
    /// falls back to an empty StatsFile when decoding throws, so one unknown-shape
    /// field would silently wipe the user's local counters — that already happened
    /// once (see the date-strategy note on load()). Every field is optional here so
    /// adding the next one can never repeat it.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        days = (try? c.decodeIfPresent([String: Double].self, forKey: .days)) as? [String: Double] ?? [:]
        top = (try? c.decodeIfPresent([String: [String: Double]].self, forKey: .top))
            as? [String: [String: Double]] ?? [:]
        remote = (try? c.decodeIfPresent([String: DeviceStats].self, forKey: .remote))
            as? [String: DeviceStats] ?? [:]
        lastSync = (try? c.decodeIfPresent(Date.self, forKey: .lastSync)) as? Date
        deviceID = (try? c.decodeIfPresent(String.self, forKey: .deviceID)) as? String
        artists = (try? c.decodeIfPresent(StatRecords.self, forKey: .artists)) as? StatRecords ?? [:]
        tracks = (try? c.decodeIfPresent(StatRecords.self, forKey: .tracks)) as? StatRecords ?? [:]
        albums = (try? c.decodeIfPresent(StatRecords.self, forKey: .albums)) as? StatRecords ?? [:]
        clock = (try? c.decodeIfPresent([String: Double].self, forKey: .clock)) as? [String: Double] ?? [:]
        seeded = (try? c.decodeIfPresent(Bool.self, forKey: .seeded)) as? Bool ?? false
    }
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

    /// Most all-time track keys kept (matches desktop stats.py's TRACK_CAP).
    static let trackCap = 2000

    /// "<weekday>-<hour>" bucket for the heatmap, weekday 0=Mon..6=Sun.
    static func clockKey(_ date: Date = Date()) -> String {
        let cal = Calendar.current
        let dow = (cal.component(.weekday, from: date) + 5) % 7
        return "\(dow)-\(cal.component(.hour, from: date))"
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

    // MARK: - All-time records (artists / tracks / albums / clock)

    /// Which map on a device file a query wants.
    enum RecordKind {
        case artists, tracks, albums

        func of(_ f: StatsFile) -> StatRecords {
            switch self {
            case .artists: return f.artists
            case .tracks:  return f.tracks
            case .albums:  return f.albums
            }
        }

        func of(_ d: DeviceStats) -> StatRecords {
            switch self {
            case .artists: return d.artists ?? [:]
            case .tracks:  return d.tracks ?? [:]
            case .albums:  return d.albums ?? [:]
            }
        }
    }

    /// Merge one record map across devices, using the same rule the day and top
    /// maps use: our own device's local vs gist copy is de-duplicated (max per
    /// field), every OTHER device is genuinely separate listening and adds.
    static func mergedRecords(_ f: StatsFile, _ kind: RecordKind) -> StatRecords {
        var remote = f.remote.mapValues { kind.of($0) }
        let own = f.deviceID.flatMap { remote.removeValue(forKey: $0) } ?? [:]
        let local = kind.of(f)
        var merged: StatRecords = [:]
        for k in Set(local.keys).union(own.keys) {
            merged[k] = (local[k] ?? StatRecord()).maxed(own[k] ?? StatRecord())
        }
        for dev in remote.values {
            for (k, rec) in dev {
                merged[k] = (merged[k] ?? StatRecord()).added(rec)
            }
        }
        return merged
    }

    /// How a chart is ordered.
    enum RankBy { case time, plays }

    /// Ranked entries of one kind. Keys are returned as-is; use `displayName`.
    static func ranked(_ f: StatsFile, _ kind: RecordKind, by: RankBy = .time,
                       n: Int = 50) -> [(key: String, rec: StatRecord)] {
        mergedRecords(f, kind)
            .sorted { a, b in
                by == .time ? a.value.s > b.value.s : (a.value.n, a.value.s) > (b.value.n, b.value.s)
            }
            .prefix(n)
            .map { (key: $0.key, rec: $0.value) }
    }

    /// Track keys are "<id>|<title>|<uploader>" and album keys "<album>|<artist>";
    /// artist keys are the bare name. Returns (primary, secondary) for display.
    static func displayName(_ key: String, _ kind: RecordKind) -> (String, String) {
        let parts = key.components(separatedBy: "|")
        switch kind {
        case .artists: return (key, "")
        case .tracks:  return (parts.count > 1 ? parts[1] : key,
                               parts.count > 2 ? parts[2] : "")
        case .albums:  return (parts.first ?? key, parts.count > 1 ? parts[1] : "")
        }
    }

    /// Everything the artist detail page shows.
    static func artistDetail(_ f: StatsFile, name: String)
        -> (rec: StatRecord, tracks: [(key: String, rec: StatRecord)]) {
        let rec = mergedRecords(f, .artists)[name] ?? StatRecord()
        let tracks = mergedRecords(f, .tracks)
            .filter { $0.key.components(separatedBy: "|").last == name }
            .sorted { $0.value.s > $1.value.s }
            .map { (key: $0.key, rec: $0.value) }
        return (rec, tracks)
    }

    /// Artists whose FIRST listen falls inside [from, to) — "discovered" then.
    static func discovered(_ f: StatsFile, from: Double, to: Double) -> [String] {
        mergedRecords(f, .artists)
            .filter { $0.value.f >= from && $0.value.f < to }
            .sorted { $0.value.s > $1.value.s }
            .map(\.key)
    }

    /// 7×24 grid of seconds (row 0 = Monday), plus the busiest bucket for scaling.
    static func clockHeatmap(_ f: StatsFile) -> (grid: [[Double]], peak: Double) {
        var merged: [String: Double] = [:]
        var remote = f.remote.mapValues { $0.clock ?? [:] }
        let own = f.deviceID.flatMap { remote.removeValue(forKey: $0) } ?? [:]
        for k in Set(f.clock.keys).union(own.keys) {
            merged[k] = max(f.clock[k] ?? 0, own[k] ?? 0)
        }
        for dev in remote.values {
            for (k, secs) in dev { merged[k, default: 0] += secs }
        }
        var grid = [[Double]](repeating: [Double](repeating: 0, count: 24), count: 7)
        var peak: Double = 0
        for (key, secs) in merged {
            let parts = key.components(separatedBy: "-")
            guard parts.count == 2, let d = Int(parts[0]), let h = Int(parts[1]),
                  (0..<7).contains(d), (0..<24).contains(h) else { continue }
            grid[d][h] = secs
            peak = max(peak, secs)
        }
        return (grid, peak)
    }

    struct Recap {
        var label = ""            // "Aug 2026" / "2026"
        var total: Double = 0     // seconds in the period
        var previous: Double = 0  // seconds in the period before it
        var topArtist = ""
        var topTrack = ""
        var newArtists: [String] = []
    }

    /// Month recap when `month` is "yyyy-MM", year recap when it is "yyyy".
    /// Per-period tops come from the monthly `top` map (the all-time records have
    /// no month dimension), so they cover the same 12-month window as those charts.
    static func recap(_ f: StatsFile, period: String) -> Recap {
        let isYear = period.count == 4
        var r = Recap()
        let days = mergedDayMap(f)
        let prevPrefix: String
        if isYear {
            r.label = period
            prevPrefix = String(format: "%04d", (Int(period) ?? 0) - 1)
        } else {
            let fmt = DateFormatter()
            fmt.locale = Locale(identifier: "en_US_POSIX")
            fmt.dateFormat = "yyyy-MM"
            let out = DateFormatter()
            out.locale = Locale(identifier: "en_US_POSIX")
            out.dateFormat = "MMM yyyy"
            r.label = fmt.date(from: period).map { out.string(from: $0) } ?? period
            let parts = period.components(separatedBy: "-")
            let y = Int(parts.first ?? "") ?? 0, m = Int(parts.count > 1 ? parts[1] : "") ?? 1
            prevPrefix = m == 1 ? String(format: "%04d-12", y - 1)
                                : String(format: "%04d-%02d", y, m - 1)
        }
        for (day, secs) in days {
            if day.hasPrefix(period) { r.total += secs }
            if day.hasPrefix(prevPrefix) { r.previous += secs }
        }
        // Tops: sum every month whose key falls in the period.
        var agg: [String: Double] = [:]
        for month in monthsIn(f, period: period) {
            for (k, v) in mergedTop(f, month: month) { agg[k, default: 0] += v }
        }
        if let best = agg.max(by: { $0.value < $1.value }) {
            let parts = best.key.components(separatedBy: "|")
            r.topTrack = parts.count > 1 ? parts[1] : best.key
        }
        var byArtist: [String: Double] = [:]
        for (k, v) in agg {
            let a = k.components(separatedBy: "|").last ?? ""
            if !a.isEmpty { byArtist[a, default: 0] += v }
        }
        r.topArtist = byArtist.max(by: { $0.value < $1.value })?.key ?? ""
        if let (from, to) = periodBounds(period) {
            r.newArtists = discovered(f, from: from, to: to)
        }
        return r
    }

    /// Month keys present anywhere in the data that fall inside `period`.
    private static func monthsIn(_ f: StatsFile, period: String) -> [String] {
        var months = Set(f.top.keys)
        for d in f.remote.values { months.formUnion((d.top ?? [:]).keys) }
        return months.filter { $0.hasPrefix(period) }.sorted()
    }

    /// [start, end) epoch bounds of a "yyyy-MM" or "yyyy" period.
    private static func periodBounds(_ period: String) -> (Double, Double)? {
        var comp = DateComponents()
        let parts = period.components(separatedBy: "-")
        comp.year = Int(parts.first ?? "")
        comp.month = parts.count > 1 ? Int(parts[1]) : 1
        comp.day = 1
        let cal = Calendar.current
        guard let start = cal.date(from: comp) else { return nil }
        let unit: Calendar.Component = parts.count > 1 ? .month : .year
        guard let end = cal.date(byAdding: unit, value: 1, to: start) else { return nil }
        return (start.timeIntervalSince1970, end.timeIntervalSince1970)
    }

    /// "Aug 2026" style label for an epoch timestamp; "" when never listened.
    static func dateLabel(_ ts: Double) -> String {
        guard ts > 0 else { return "" }
        let fmt = DateFormatter()
        fmt.locale = Locale(identifier: "en_US_POSIX")
        fmt.dateFormat = "d MMM yyyy"
        return fmt.string(from: Date(timeIntervalSince1970: ts))
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
