import SwiftUI

/// Full-screen listening-stats browser (Settings → LISTEN STATS → SEE ALL).
///
/// Everything here is derived from the already-merged cross-device records in
/// `StatsShared` — this screen does no network and no counting of its own, so it
/// stays correct no matter which device did the listening.
struct StatsScreen: View {
    @ObservedObject var stats = StatsStore.shared
    @ObservedObject private var theme = ThemeManager.shared
    @Environment(\.dismiss) private var dismiss

    private enum Section: String, CaseIterable {
        case overview = "overview"
        case artists = "artists"
        case tracks = "tracks"
        case albums = "albums"
        case recap = "recap"
    }

    @State private var section: Section = .overview
    @State private var byPlays = false
    @State private var openArtist: ArtistRef?

    private var rank: StatsShared.RankBy { byPlays ? .plays : .time }

    var body: some View {
        ZStack {
            TUI.bg.ignoresSafeArea()
            VStack(spacing: 12) {
                header
                Picker("", selection: $section) {
                    ForEach(Section.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, 12)

                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        switch section {
                        case .overview: overview
                        case .artists:  chart(.artists)
                        case .tracks:   chart(.tracks)
                        case .albums:   albums
                        case .recap:    recaps
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.bottom, 24)
                }
            }
        }
        .foregroundStyle(TUI.fg)
        .font(TUI.mono())
        .tint(TUI.accent)
        .preferredColorScheme(theme.current.dark ? .dark : .light)
        // A sheet, matching how Settings presents its other sub-screens (and
        // stacking cleanly on top of the sheet this screen itself sits in).
        .sheet(item: $openArtist) { ref in
            ArtistStatsScreen(name: ref.id, stats: stats)
        }
    }

    private var header: some View {
        HStack {
            Text("◆ LISTEN STATS").font(TUI.mono(15, .bold)).foregroundStyle(TUI.accent)
            Spacer()
            if section == .artists || section == .tracks || section == .albums {
                Picker("", selection: $byPlays) {
                    Text("time").tag(false)
                    Text("plays").tag(true)
                }
                .pickerStyle(.segmented).frame(width: 130)
            }
            Button { dismiss() } label: {
                Text("✕").font(TUI.mono(16, .bold)).foregroundStyle(TUI.dim)
            }
        }
        .padding(.horizontal, 12).padding(.top, 12)
    }

    // MARK: - Overview

    private var overview: some View {
        let totals = StatsShared.totals(stats.file)
        let streak = StatsShared.streak(stats.file)
        let best = StatsShared.bestDay(stats.file)
        let artistCount = StatsShared.mergedRecords(stats.file, .artists).count
        let trackCount = StatsShared.mergedRecords(stats.file, .tracks).count
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 0) {
                tile("today", StatsShared.fmtMins(totals.today))
                tile("7 days", StatsShared.fmtMins(totals.week))
                tile("all time", StatsShared.fmtMins(totals.all))
            }
            HStack(spacing: 0) {
                tile("artists", "\(artistCount)")
                tile("tracks", "\(trackCount)")
                tile("streak", "\(streak.current)d")
            }
            line("longest streak", "\(streak.longest) days")
            line("this year", StatsShared.fmtMins(StatsShared.yearTotal(stats.file)))
            if !best.day.isEmpty {
                line("biggest day", "\(best.day) · \(StatsShared.fmtMins(best.secs))")
            }
            heatmap
        }
    }

    /// 7×24 grid — rows Mon…Sun, columns hours. Intensity is the accent colour's
    /// opacity, so it follows the active theme like everything else.
    private var heatmap: some View {
        let (grid, peak) = StatsShared.clockHeatmap(stats.file)
        let names = ["M", "T", "W", "T", "F", "S", "S"]
        return VStack(alignment: .leading, spacing: 4) {
            Text("when you listen").font(TUI.mono(11, .bold)).foregroundStyle(TUI.dim)
            ForEach(0..<7, id: \.self) { d in
                HStack(spacing: 2) {
                    Text(names[d]).font(TUI.mono(9)).foregroundStyle(TUI.dim)
                        .frame(width: 10)
                    ForEach(0..<24, id: \.self) { h in
                        RoundedRectangle(cornerRadius: 1)
                            .fill(TUI.accent.opacity(peak > 0
                                                     ? 0.08 + 0.92 * (grid[d][h] / peak)
                                                     : 0.08))
                            .frame(height: 11)
                    }
                }
            }
            HStack(spacing: 2) {
                Text(" ").font(TUI.mono(9)).frame(width: 10)
                ForEach([0, 6, 12, 18], id: \.self) { h in
                    Text("\(h)h").font(TUI.mono(8)).foregroundStyle(TUI.dim)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .padding(8)
        .background(TUI.panel.opacity(0.55))
        .cornerRadius(4)
    }

    // MARK: - Charts

    private func chart(_ kind: StatsShared.RecordKind) -> some View {
        let rows = StatsShared.ranked(stats.file, kind, by: rank, n: 200)
        return VStack(alignment: .leading, spacing: 2) {
            if rows.isEmpty { empty }
            ForEach(Array(rows.enumerated()), id: \.offset) { i, r in
                let (primary, secondary) = StatsShared.displayName(r.key, kind)
                Button {
                    if kind == .artists { openArtist = ArtistRef(id: primary) }
                } label: {
                    chartRow(i: i, primary: primary, secondary: secondary, rec: r.rec)
                }
                .buttonStyle(.plain)
                .disabled(kind != .artists)
            }
        }
    }

    private var albums: some View { chart(.albums) }

    private func chartRow(i: Int, primary: String, secondary: String,
                          rec: StatRecord) -> some View {
        HStack(spacing: 8) {
            Text("\(i + 1).").foregroundStyle(TUI.dim)
                .frame(width: 30, alignment: .trailing)
            VStack(alignment: .leading, spacing: 0) {
                Text(primary).foregroundStyle(TUI.fg).lineLimit(1)
                if !secondary.isEmpty {
                    Text(secondary).font(TUI.mono(10)).foregroundStyle(TUI.dim).lineLimit(1)
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 0) {
                Text(StatsShared.fmtMins(rec.s)).foregroundStyle(TUI.accent)
                Text("\(rec.n) play\(rec.n == 1 ? "" : "s")")
                    .font(TUI.mono(10)).foregroundStyle(TUI.dim)
            }
        }
        .font(TUI.mono(12))
        .padding(.vertical, 3)
    }

    // MARK: - Recaps

    private var recaps: some View {
        let now = Date()
        let cal = Calendar.current
        let months: [String] = (0..<6).compactMap { i in
            cal.date(byAdding: .month, value: -i, to: now).map(StatsShared.monthKey)
        }
        let year = String(StatsShared.monthKey(now).prefix(4))
        return VStack(alignment: .leading, spacing: 10) {
            recapCard(StatsShared.recap(stats.file, period: year))
            ForEach(months, id: \.self) { m in
                recapCard(StatsShared.recap(stats.file, period: m))
            }
        }
    }

    private func recapCard(_ r: StatsShared.Recap) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(r.label).font(TUI.mono(13, .bold)).foregroundStyle(TUI.accent)
                Spacer()
                Text(StatsShared.fmtMins(r.total)).foregroundStyle(TUI.fg)
            }
            if r.previous > 0 {
                let delta = r.total - r.previous
                Text("\(delta >= 0 ? "↑" : "↓") \(StatsShared.fmtMins(abs(delta))) vs previous")
                    .font(TUI.mono(10)).foregroundStyle(TUI.dim)
            }
            if !r.topArtist.isEmpty { line("top artist", r.topArtist) }
            if !r.topTrack.isEmpty { line("top track", r.topTrack) }
            if !r.newArtists.isEmpty {
                line("new artists", "\(r.newArtists.count)")
                Text(r.newArtists.prefix(5).joined(separator: " · "))
                    .font(TUI.mono(10)).foregroundStyle(TUI.dim).lineLimit(2)
            }
        }
        .padding(8)
        .background(TUI.panel.opacity(0.55))
        .cornerRadius(4)
    }

    // MARK: - Small pieces

    private var empty: some View {
        Text("nothing tracked yet — play something")
            .font(TUI.mono(12)).foregroundStyle(TUI.dim).padding(.vertical, 20)
    }

    private func tile(_ label: String, _ value: String) -> some View {
        VStack(spacing: 2) {
            Text(value).font(TUI.mono(15, .bold)).foregroundStyle(TUI.accent)
            Text(label).font(TUI.mono(10)).foregroundStyle(TUI.dim)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 6)
        .background(TUI.panel.opacity(0.55))
        .cornerRadius(4)
    }

    private func line(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label).foregroundStyle(TUI.dim)
            Spacer()
            Text(value).foregroundStyle(TUI.fg).lineLimit(1)
        }
        .font(TUI.mono(12))
    }
}

/// One artist's page: totals, when you found them, and their tracks.
struct ArtistStatsScreen: View {
    let name: String
    @ObservedObject var stats: StatsStore
    @ObservedObject private var theme = ThemeManager.shared
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let detail = StatsShared.artistDetail(stats.file, name: name)
        ZStack {
            TUI.bg.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("◆ \(name)").font(TUI.mono(15, .bold))
                        .foregroundStyle(TUI.accent).lineLimit(2)
                    Spacer()
                    Button { dismiss() } label: {
                        Text("✕").font(TUI.mono(16, .bold)).foregroundStyle(TUI.dim)
                    }
                }
                HStack(spacing: 0) {
                    tile("listened", StatsShared.fmtMins(detail.rec.s))
                    tile("plays", "\(detail.rec.n)")
                    tile("tracks", "\(detail.tracks.count)")
                }
                if detail.rec.f > 0 {
                    HStack {
                        Text("first heard").foregroundStyle(TUI.dim)
                        Spacer()
                        Text(StatsShared.dateLabel(detail.rec.f)).foregroundStyle(TUI.fg)
                    }
                    .font(TUI.mono(12))
                    HStack {
                        Text("last heard").foregroundStyle(TUI.dim)
                        Spacer()
                        Text(StatsShared.dateLabel(detail.rec.l)).foregroundStyle(TUI.fg)
                    }
                    .font(TUI.mono(12))
                }
                ScrollView {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(Array(detail.tracks.enumerated()), id: \.offset) { i, t in
                            let (title, _) = StatsShared.displayName(t.key, .tracks)
                            HStack(spacing: 8) {
                                Text("\(i + 1).").foregroundStyle(TUI.dim)
                                    .frame(width: 30, alignment: .trailing)
                                Text(title).foregroundStyle(TUI.fg).lineLimit(1)
                                Spacer()
                                Text(StatsShared.fmtMins(t.rec.s)).foregroundStyle(TUI.accent)
                            }
                            .font(TUI.mono(12)).padding(.vertical, 3)
                        }
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(12)
        }
        .foregroundStyle(TUI.fg)
        .font(TUI.mono())
        .preferredColorScheme(theme.current.dark ? .dark : .light)
    }

    private func tile(_ label: String, _ value: String) -> some View {
        VStack(spacing: 2) {
            Text(value).font(TUI.mono(15, .bold)).foregroundStyle(TUI.accent)
            Text(label).font(TUI.mono(10)).foregroundStyle(TUI.dim)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 6)
        .background(TUI.panel.opacity(0.55))
        .cornerRadius(4)
    }
}

/// Drives `.fullScreenCover(item:)` — a wrapper rather than making String itself
/// Identifiable, which would be a retroactive stdlib conformance the whole app pays for.
struct ArtistRef: Identifiable, Equatable {
    let id: String
}
