import SwiftUI
import WidgetKit

/// Home-screen widget: listening time across all devices (bar graph + totals).
/// Reads ONLY the stats.json the app maintains in the shared App Group — no
/// network, no token, no Python. The app pokes reloadAllTimelines() after every
/// flush/sync; the .after(midnight) policy rolls the bars over even if the app
/// never wakes that day.
@main
struct YTMusicWidgetBundle: WidgetBundle {
    var body: some Widget {
        YTMusicStatsWidget()
        NowPlayingWidget()
        StatsLockWidget()
    }
}

/// The app's active theme, resolved to Colors (falls back to the classic
/// black/green TUI look when the app hasn't published a theme yet).
struct WPalette {
    let bg: Color
    let fg: Color
    let dim: Color
    let accent: Color

    static let fallback = WPalette(
        bg: Color.black,
        fg: Color(red: 0.92, green: 0.94, blue: 0.92),
        dim: Color(red: 0.55, green: 0.60, blue: 0.55),
        accent: Color(red: 0.30, green: 0.85, blue: 0.45))

    static func load() -> WPalette {
        guard let t = WidgetTheme.load() else { return .fallback }
        return WPalette(bg: WidgetTheme.color(t.bg),
                        fg: WidgetTheme.color(t.fg),
                        dim: WidgetTheme.color(t.dim),
                        accent: WidgetTheme.color(t.accent))
    }
}

struct StatsEntry: TimelineEntry {
    let date: Date
    let days: [(key: String, secs: Double)]   // last 7, oldest first
    let today: Double
    let week: Double
    let all: Double
    let hasData: Bool
    var palette: WPalette = .fallback
}

struct StatsProvider: TimelineProvider {
    func placeholder(in context: Context) -> StatsEntry { Self.sample }

    func getSnapshot(in context: Context, completion: @escaping (StatsEntry) -> Void) {
        completion(context.isPreview ? Self.sample : Self.load())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<StatsEntry>) -> Void) {
        let next = Calendar.current.startOfDay(
            for: Date().addingTimeInterval(86400))   // next local midnight
        completion(Timeline(entries: [Self.load()], policy: .after(next)))
    }

    static func load() -> StatsEntry {
        let f = StatsShared.load()
        let t = StatsShared.totals(f)
        return StatsEntry(date: Date(),
                          days: StatsShared.mergedDays(f, last: 7).map { ($0.0, $0.1) },
                          today: t.today, week: t.week, all: t.all,
                          hasData: t.all > 0,
                          palette: WPalette.load())
    }

    static var sample: StatsEntry {
        let days = StatsShared.lastDays(7)
        let secs: [Double] = [1800, 3600, 900, 5400, 2700, 4500, 1860]
        return StatsEntry(date: Date(),
                          days: zip(days, secs).map { ($0, $1) },
                          today: 1860, week: 20760, all: 145_000, hasData: true)
    }
}

struct YTMusicStatsWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "YTMusicStats", provider: StatsProvider()) { entry in
            StatsWidgetView(entry: entry)
        }
        .configurationDisplayName("Listening time")
        .description("Minutes listened across all your devices.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

// MARK: - Views (TUI look: black, mono, accent green)

private enum W {
    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}

struct StatsWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: StatsEntry
    private var p: WPalette { entry.palette }

    var body: some View {
        Group {
            if !entry.hasData {
                VStack(spacing: 6) {
                    Text("♪").font(W.mono(22)).foregroundStyle(p.accent)
                    Text("play something in\nYT Music")
                        .font(W.mono(11)).foregroundStyle(p.dim)
                        .multilineTextAlignment(.center)
                }
            } else if family == .systemSmall {
                smallView
            } else {
                mediumView
            }
        }
        .widgetBackground(p.bg)
    }

    private var smallView: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("♪ listened").font(W.mono(11, .bold)).foregroundStyle(p.accent)
            Spacer(minLength: 2)
            Text(StatsShared.fmtMins(entry.today))
                .font(W.mono(26, .bold)).foregroundStyle(p.fg)
                .minimumScaleFactor(0.6).lineLimit(1)
            Text("today").font(W.mono(11)).foregroundStyle(p.dim)
            Spacer(minLength: 2)
            Text("7d \(StatsShared.fmtMins(entry.week))")
                .font(W.mono(12)).foregroundStyle(p.dim)
                .minimumScaleFactor(0.7).lineLimit(1)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }

    private var mediumView: some View {
        HStack(spacing: 14) {
            bars
            VStack(alignment: .trailing, spacing: 4) {
                Text("♪ listened").font(W.mono(11, .bold)).foregroundStyle(p.accent)
                Spacer(minLength: 0)
                statLine("today", entry.today, bold: true)
                statLine("7 days", entry.week)
                statLine("all", entry.all)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func statLine(_ label: String, _ secs: Double, bold: Bool = false) -> some View {
        VStack(alignment: .trailing, spacing: 0) {
            Text(StatsShared.fmtMins(secs))
                .font(W.mono(bold ? 17 : 13, bold ? .bold : .regular))
                .foregroundStyle(bold ? p.fg : p.dim)
                .minimumScaleFactor(0.7).lineLimit(1)
            Text(label).font(W.mono(9)).foregroundStyle(p.dim)
        }
    }

    private var bars: some View {
        let peak = max(entry.days.map(\.secs).max() ?? 0, 1)
        return GeometryReader { geo in
            HStack(alignment: .bottom, spacing: 5) {
                ForEach(Array(entry.days.enumerated()), id: \.offset) { i, day in
                    let isToday = i == entry.days.count - 1
                    VStack(spacing: 3) {
                        RoundedRectangle(cornerRadius: 2)
                            .fill(isToday ? p.accent : p.accent.opacity(0.45))
                            .frame(height: max(3, (geo.size.height - 16)
                                                  * day.secs / peak))
                        Text(weekdayInitial(day.key))
                            .font(W.mono(9))
                            .foregroundStyle(isToday ? p.accent : p.dim)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity,
                           alignment: .bottom)
                }
            }
        }
    }

    private func weekdayInitial(_ dayKey: String) -> String {
        let fmt = DateFormatter()
        fmt.locale = Locale(identifier: "en_US_POSIX")
        fmt.dateFormat = "yyyy-MM-dd"
        guard let d = fmt.date(from: dayKey) else { return "?" }
        let wd = Calendar.current.component(.weekday, from: d)
        return ["S", "M", "T", "W", "T", "F", "S"][wd - 1]
    }
}

extension View {
    /// iOS 17 requires containerBackground for widgets; 16 uses a plain
    /// background. (Shared by every widget in this extension — accessory
    /// families skip the padding via widgetAccessoryBackground below.)
    @ViewBuilder
    func widgetBackground(_ color: Color) -> some View {
        if #available(iOSApplicationExtension 17.0, *) {
            containerBackground(for: .widget) { color }
        } else {
            padding(12).background(color)
        }
    }

    /// Accessory (lock-screen) variant: no padding hack, transparent container.
    @ViewBuilder
    func widgetAccessoryBackground() -> some View {
        if #available(iOSApplicationExtension 17.0, *) {
            containerBackground(for: .widget) { Color.clear }
        } else {
            self
        }
    }
}
