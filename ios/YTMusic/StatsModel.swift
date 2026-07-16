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
}

struct StatsFile: Codable {
    var days: [String: Double] = [:]            // this install's own counters
    var remote: [String: DeviceStats] = [:]     // last gist pull, keyed by device id
    var lastSync: Date? = nil
    var deviceID: String? = nil                 // ours — lets the widget dedup exactly
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
