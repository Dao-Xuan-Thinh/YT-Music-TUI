import SwiftUI
import WidgetKit

/// Lock-screen listening-time accessories (separate widget kind from the
/// home-screen stats widget; same StatsProvider/timeline). Lock-screen
/// rendering is monochrome/tinted — no theme palette here, just
/// widgetAccentable highlights.
struct StatsLockWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "YTMusicStatsLock",
                            provider: StatsProvider()) { entry in
            StatsLockView(entry: entry)
        }
        .configurationDisplayName("Listening time (lock screen)")
        .description("Today's minutes on your lock screen.")
        .supportedFamilies([.accessoryCircular, .accessoryRectangular,
                            .accessoryInline])
    }
}

struct StatsLockView: View {
    @Environment(\.widgetFamily) private var family
    let entry: StatsEntry
    private func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }

    var body: some View {
        Group {
            switch family {
            case .accessoryCircular: circular
            case .accessoryInline: inline
            default: rectangular
            }
        }
        .widgetAccessoryBackground()
    }

    private var circular: some View {
        ZStack {
            AccessoryWidgetBackground()
            // Gauge fills against a 2h/day listening target.
            Gauge(value: min(entry.today / 7200, 1)) {
                Text("♪")
            } currentValueLabel: {
                Text(StatsShared.fmtMins(entry.today))
                    .font(mono(11, .bold)).widgetAccentable()
                    .minimumScaleFactor(0.6)
            }
            .gaugeStyle(.accessoryCircularCapacity)
        }
    }

    private var rectangular: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text("♪ listened").font(mono(11, .bold)).widgetAccentable()
            Text("today  \(StatsShared.fmtMins(entry.today))").font(mono(11))
            Text("7 days \(StatsShared.fmtMins(entry.week))").font(mono(11))
                .opacity(0.75)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var inline: some View {
        Text("♪ \(StatsShared.fmtMins(entry.today)) today")
    }
}
