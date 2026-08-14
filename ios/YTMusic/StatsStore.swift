import Combine
import Foundation
import WidgetKit

/// Listen-time accumulator + gist sync (app side; the widget only reads the file
/// StatsShared points at). Mirrors the desktop `stats.py`:
///   - `tick()` is fed sub-second playback deltas from PlaybackService
///   - counters buffer in memory and flush at most once a minute (plus on
///     backgrounding), then poke WidgetKit
///   - sync = one private gist ("ytm-tui listen stats"), one file per device,
///     so cross-device merging is conflict-free by construction. Fail-silent.
///
/// Not actor-annotated (same style as UpdateChecker): all mutable state is only
/// touched on the main queue — tick() comes from PlaybackService's main-queue
/// time observer, UI calls come from SwiftUI, and the sync worker hops back via
/// DispatchQueue.main.
final class StatsStore: ObservableObject {
    static let shared = StatsStore()

    @Published private(set) var file: StatsFile
    @Published private(set) var syncStatus = ""   // "" | "synced" | error text

    private var dirty = false
    private var lastWrite = Date.distantPast
    // Current play, for play counting only (never persisted).
    private var playSeconds: Double = 0
    private var playCounted = false
    private var playDuration: Double = 0
    private var lastSyncAttempt = Date.distantPast
    private var syncing = false

    private static let marker = "ytm-tui listen stats"
    private static let api = "https://api.github.com"

    private init() {
        var f = StatsShared.load()
        f.deviceID = AppConfig.shared.statsDeviceID
        file = f
    }

    // MARK: - Accumulation

    /// Announce that a new play started. Play COUNTS (as opposed to seconds) need
    /// this: without it a repeat-one loop looks like one endless play, since the
    /// track identity never changes between ticks.
    func beginTrack(_ track: Track?) {
        playSeconds = 0
        playCounted = false
        playDuration = Double(track?.duration ?? 0)
    }

    /// Add listened seconds (called every 0.5s while audio actually advances),
    /// attributed to `track` for the monthly top charts and the all-time records.
    func tick(_ delta: Double, track: Track? = nil) {
        guard delta > 0 else { return }
        let now = Date().timeIntervalSince1970
        file.days[StatsShared.dayKey(), default: 0] += delta
        file.clock[StatsShared.clockKey(), default: 0] += delta
        if let t = track, !t.id.isEmpty {
            let key = "\(t.id)|\(t.title)|\(t.uploader)"
            file.top[StatsShared.monthKey(), default: [:]][key, default: 0] += delta

            // A play is credited once the listen passes half the track, capped at
            // 30s — so a skipped intro never counts and a long track doesn't have
            // to finish. Seconds accrue regardless.
            playSeconds += delta
            let threshold = playDuration > 0 ? min(30, playDuration / 2) : 30
            let credit = !playCounted && playSeconds >= threshold
            if credit { playCounted = true }

            bump(&file.tracks, key, delta, credit, now)
            if !t.uploader.isEmpty { bump(&file.artists, t.uploader, delta, credit, now) }
            if let album = t.album, !album.isEmpty {
                bump(&file.albums, "\(album)|\(t.uploader)", delta, credit, now)
            }
        }
        dirty = true
        if Date().timeIntervalSince(lastWrite) > 60 { flush() }
    }

    private func bump(_ map: inout StatRecords, _ key: String, _ delta: Double,
                      _ countPlay: Bool, _ now: Double) {
        var rec = map[key] ?? StatRecord()
        rec.s += delta
        if countPlay { rec.n += 1 }
        if rec.f == 0 { rec.f = now }
        rec.l = now
        map[key] = rec
    }

    func flush(reloadWidget: Bool = false) {
        if dirty {
            dirty = false
            lastWrite = Date()
            pruneTop()
            write(file)
        }
        if reloadWidget { WidgetCenter.shared.reloadAllTimelines() }
    }

    /// Newest 12 months, top 300 keys per month (matches desktop stats.py).
    /// The all-time track map is capped too — it is the only one that grows without
    /// bound. Artists and albums are left alone: there are orders of magnitude fewer
    /// of them, and dropping one would lose its "first listened" date forever.
    private func pruneTop() {
        for month in file.top.keys.sorted(by: >).dropFirst(12) {
            file.top[month] = nil
        }
        for (month, entries) in file.top where entries.count > 300 {
            file.top[month] = Dictionary(uniqueKeysWithValues:
                entries.sorted { $0.value > $1.value }.prefix(300).map { ($0, $1) })
        }
        if file.tracks.count > StatsShared.trackCap {
            file.tracks = Dictionary(uniqueKeysWithValues:
                file.tracks.sorted { $0.value.s > $1.value.s }
                    .prefix(StatsShared.trackCap).map { ($0, $1) })
        }
    }

    private func write(_ f: StatsFile) {
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        enc.dateEncodingStrategy = .iso8601
        if let data = try? enc.encode(f) {
            try? data.write(to: StatsShared.storeURL(), options: .atomic)
        }
    }

    var lastSyncLabel: String {
        if AppConfig.shared.statsToken.isEmpty { return "not configured" }
        if !syncStatus.isEmpty && syncStatus != "synced" { return syncStatus }
        guard let ts = file.lastSync else { return "waiting for first sync" }
        let mins = Int(-ts.timeIntervalSinceNow / 60)
        return mins < 1 ? "synced just now" : "synced \(mins) min ago"
    }

    // MARK: - Gist sync

    /// Full cycle on a background queue; throttled to one attempt / 10 min
    /// unless forced. Same protocol as the desktop's stats.py. `completion`
    /// fires on the main queue after the cycle ends (or immediately when the
    /// sync is skipped) — the background-refresh task awaits it so the process
    /// isn't suspended mid-PATCH. Main-actor: reads LibraryStore for the
    /// library blob (network work still hops to a background queue).
    @MainActor
    func sync(force: Bool = false, completion: (() -> Void)? = nil) {
        let token = AppConfig.shared.statsToken
        let deviceID = AppConfig.shared.statsDeviceID
        let deviceName = AppConfig.shared.statsDeviceName
        guard !token.isEmpty, !syncing else { completion?(); return }
        guard force || Date().timeIntervalSince(lastSyncAttempt) > 600 else {
            completion?(); return
        }
        lastSyncAttempt = Date()
        syncing = true
        file.deviceID = deviceID
        let localDays = file.days
        let localTop = file.top
        let localRecords = LocalRecords(artists: file.artists, tracks: file.tracks,
                                        albums: file.albums, clock: file.clock)
        // The library blob (liked/playlists/sessions + tombstones) rides in our
        // gist file; the merged state comes back and is applied below.
        let libraryBlob = LibraryStore.shared.exportSync(deviceName: deviceName)
        let gistID = AppConfig.shared.statsGistID
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let result = Self.runSync(token: token, deviceID: deviceID,
                                      deviceName: deviceName, gistID: gistID,
                                      localDays: localDays, localTop: localTop,
                                      localRecords: localRecords,
                                      libraryBlob: libraryBlob)
            DispatchQueue.main.async {
                defer { completion?() }
                guard let self else { return }
                self.syncing = false
                switch result {
                case .success(let outcome):
                    if let id = outcome.newGistID {
                        AppConfig.shared.statsGistID = id
                    }
                    // Merge-max our own gist copy back in (protects a wiped
                    // store) without clobbering seconds ticked during the sync.
                    for (day, secs) in outcome.mergedDays
                    where secs > (self.file.days[day] ?? 0) {
                        self.file.days[day] = secs
                    }
                    // Same protection for the all-time maps: take whichever side is
                    // ahead field-by-field, so seconds ticked DURING the sync survive
                    // and a re-pulled copy of our own file can't double-count.
                    self.file.artists = Self.maxRecords(self.file.artists,
                                                        outcome.mergedRecords.artists)
                    self.file.tracks = Self.maxRecords(self.file.tracks,
                                                       outcome.mergedRecords.tracks)
                    self.file.albums = Self.maxRecords(self.file.albums,
                                                       outcome.mergedRecords.albums)
                    for (k, v) in outcome.mergedRecords.clock
                    where v > (self.file.clock[k] ?? 0) {
                        self.file.clock[k] = v
                    }
                    self.file.remote = outcome.remote
                    self.file.lastSync = Date()
                    self.syncStatus = "synced"
                    self.dirty = true
                    self.flush(reloadWidget: true)
                    let mergedLib = outcome.mergedLibrary
                    Task { @MainActor in
                        LibraryStore.shared.applySync(mergedLib)
                    }
                    DebugLog.shared.log("stats",
                        "synced \(outcome.remote.count) device file(s)")
                case .failure(let err):
                    self.syncStatus = err.label
                    DebugLog.shared.log("stats", "sync failed: \(err.label)")
                }
            }
        }
    }

    private enum SyncError: Error {
        case badToken, rateLimited, notFound, network
        var label: String {
            switch self {
            case .badToken: return "token rejected"
            case .rateLimited: return "rate limited"
            case .notFound, .network: return "network error"
            }
        }
    }

    private struct SyncOutcome {
        let remote: [String: DeviceStats]
        let mergedDays: [String: Double]
        let newGistID: String?
        let mergedLibrary: LibraryBlob
        let mergedRecords: LocalRecords
    }

    /// The all-time maps, passed to the background sync and merged back after.
    struct LocalRecords {
        var artists: StatRecords = [:]
        var tracks: StatRecords = [:]
        var albums: StatRecords = [:]
        var clock: [String: Double] = [:]
    }

    /// Blocking sync (background queue only): pull all device files, merge the
    /// library blobs, push ours (days + monthly top + merged library).
    private static func runSync(
        token: String, deviceID: String, deviceName: String, gistID: String,
        localDays: [String: Double], localTop: [String: [String: Double]],
        localRecords: LocalRecords, libraryBlob: LibraryBlob
    ) -> Result<SyncOutcome, SyncError> {
        do {
            var id = gistID
            var pulled: [String: Any]? = nil
            if id.isEmpty {
                id = try findGist(token: token)
            }
            if !id.isEmpty {
                do {
                    pulled = try request("GET", "/gists/\(id)", token: token)
                } catch SyncError.notFound {
                    // Cached id points at a deleted gist → rediscover once.
                    id = try findGist(token: token)
                    pulled = id.isEmpty ? nil
                        : try request("GET", "/gists/\(id)", token: token)
                }
            }
            var remote: [String: DeviceStats] = [:]
            var remoteLibs: [LibraryBlob] = []   // other devices' blobs (ours excluded)
            if let files = pulled?["files"] as? [String: Any] {
                for (name, info) in files {
                    guard name.hasPrefix("ytm-stats-"), name.hasSuffix(".json"),
                          let content = (info as? [String: Any])?["content"] as? String,
                          let data = content.data(using: .utf8),
                          let parsed = try? JSONSerialization.jsonObject(with: data)
                            as? [String: Any]
                    else { continue }
                    let dev = String(name.dropFirst("ytm-stats-".count)
                                         .dropLast(".json".count))
                    let days = doubleMap(parsed["days"])
                    var top: [String: [String: Double]] = [:]
                    for (month, entries) in (parsed["top"] as? [String: Any]) ?? [:] {
                        top[month] = doubleMap(entries)
                    }
                    remote[dev] = DeviceStats(
                        device: parsed["device"] as? String ?? String(dev.prefix(8)),
                        days: days, top: top,
                        artists: recordMap(parsed["artists"]),
                        tracks: recordMap(parsed["tracks"]),
                        albums: recordMap(parsed["albums"]),
                        clock: doubleMap(parsed["clock"]))
                    if dev != deviceID, let lib = parsed["library"],
                       let libData = try? JSONSerialization.data(withJSONObject: lib),
                       let blob = try? JSONDecoder().decode(LibraryBlob.self, from: libData) {
                        remoteLibs.append(blob)
                    }
                }
            }
            // Cross-device library merge: our fresh export + everyone else's.
            let mergedLibrary = LibrarySync.merge([libraryBlob] + remoteLibs)
            // Merge-max our own remote copy into the local counters, then push.
            var days = localDays
            for (day, secs) in remote[deviceID]?.days ?? [:]
            where secs > (days[day] ?? 0) {
                days[day] = secs
            }
            // Same merge-max as days, per field: our own gist copy can be ahead of
            // a wiped local store, but re-pulling it must never inflate the counts.
            var records = localRecords
            if let own = remote[deviceID] {
                records.artists = maxRecords(records.artists, own.artists ?? [:])
                records.tracks = maxRecords(records.tracks, own.tracks ?? [:])
                records.albums = maxRecords(records.albums, own.albums ?? [:])
                for (k, v) in own.clock ?? [:] where v > (records.clock[k] ?? 0) {
                    records.clock[k] = v
                }
            }
            var payload: [String: Any] = ["device": deviceName, "days": days,
                                          "top": localTop,
                                          "artists": recordPayload(records.artists),
                                          "tracks": recordPayload(records.tracks),
                                          "albums": recordPayload(records.albums),
                                          "clock": records.clock]
            // Publish the MERGED library so this file already reflects
            // everyone's edits the next time another device pulls.
            if let libData = try? JSONEncoder().encode(mergedLibrary),
               let libObj = try? JSONSerialization.jsonObject(with: libData) {
                payload["library"] = libObj
            }
            let content = String(
                data: try JSONSerialization.data(withJSONObject: payload),
                encoding: .utf8) ?? "{}"
            let fileBody = ["files": ["ytm-stats-\(deviceID).json":
                                        ["content": content]]]
            if id.isEmpty {
                var body = fileBody as [String: Any]
                body["description"] = marker
                body["public"] = false
                let created = try request("POST", "/gists", token: token, body: body)
                id = created["id"] as? String ?? ""
            } else {
                _ = try request("PATCH", "/gists/\(id)", token: token, body: fileBody)
            }
            remote[deviceID] = DeviceStats(device: deviceName, days: days,
                                           top: localTop,
                                           artists: records.artists,
                                           tracks: records.tracks,
                                           albums: records.albums,
                                           clock: records.clock)
            return .success(SyncOutcome(remote: remote, mergedDays: days,
                                        newGistID: id == gistID ? nil : id,
                                        mergedLibrary: mergedLibrary,
                                        mergedRecords: records))
        } catch let err as SyncError {
            return .failure(err)
        } catch {
            return .failure(.network)
        }
    }

    /// {"key": {"s":…,"n":…,"f":…,"l":…}} → StatRecords. Missing/odd fields read
    /// as 0 so a file written by a different client version can never throw.
    private static func recordMap(_ any: Any?) -> StatRecords {
        guard let raw = any as? [String: Any] else { return [:] }
        var out: StatRecords = [:]
        for (k, v) in raw {
            guard let d = v as? [String: Any] else { continue }
            out[k] = StatRecord(s: (d["s"] as? NSNumber)?.doubleValue ?? 0,
                                n: (d["n"] as? NSNumber)?.intValue ?? 0,
                                f: (d["f"] as? NSNumber)?.doubleValue ?? 0,
                                l: (d["l"] as? NSNumber)?.doubleValue ?? 0)
        }
        return out
    }

    private static func recordPayload(_ recs: StatRecords) -> [String: Any] {
        recs.mapValues { ["s": $0.s, "n": $0.n, "f": $0.f, "l": $0.l] }
    }

    private static func maxRecords(_ a: StatRecords, _ b: StatRecords) -> StatRecords {
        var out = a
        for (k, rec) in b { out[k] = (out[k] ?? StatRecord()).maxed(rec) }
        return out
    }

    private static func doubleMap(_ any: Any?) -> [String: Double] {
        (any as? [String: Double])
            ?? (any as? [String: Any])?
                .compactMapValues { ($0 as? NSNumber)?.doubleValue } ?? [:]
    }

    /// Oldest gist whose description matches the marker ('' if none) — oldest so
    /// two devices that raced a creation converge on the same gist forever.
    private static func findGist(token: String) throws -> String {
        let list = try requestArray("GET", "/gists?per_page=100", token: token)
        let ours = list
            .filter { $0["description"] as? String == marker }
            .sorted { ($0["created_at"] as? String ?? "")
                      < ($1["created_at"] as? String ?? "") }
        return ours.first?["id"] as? String ?? ""
    }

    // MARK: - Tiny synchronous HTTP helper (background queue only)

    private static func rawRequest(_ method: String, _ path: String, token: String,
                                   body: [String: Any]?) throws -> Data {
        var req = URLRequest(url: URL(string: api + path)!, timeoutInterval: 10)
        req.httpMethod = method
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        req.setValue("2022-11-28", forHTTPHeaderField: "X-GitHub-Api-Version")
        if let body {
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let sem = DispatchSemaphore(value: 0)
        var out: (Data?, HTTPURLResponse?) = (nil, nil)
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            out = (data, resp as? HTTPURLResponse)
            sem.signal()
        }.resume()
        _ = sem.wait(timeout: .now() + 15)
        guard let resp = out.1, let data = out.0 else { throw SyncError.network }
        switch resp.statusCode {
        case 200..<300: return data
        case 401: throw SyncError.badToken
        case 403, 429:
            if resp.value(forHTTPHeaderField: "x-ratelimit-remaining") == "0" {
                throw SyncError.rateLimited
            }
            // 403 without rate-limit = fine-grained token missing the Gists
            // permission — surface it as a token problem, not "network".
            throw SyncError.badToken
        case 404: throw SyncError.notFound
        default: throw SyncError.network
        }
    }

    private static func request(_ method: String, _ path: String, token: String,
                                body: [String: Any]? = nil) throws -> [String: Any] {
        let data = try rawRequest(method, path, token: token, body: body)
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
    }

    private static func requestArray(_ method: String, _ path: String, token: String)
        throws -> [[String: Any]] {
        let data = try rawRequest(method, path, token: token, body: nil)
        return (try? JSONSerialization.jsonObject(with: data)) as? [[String: Any]] ?? []
    }
}
