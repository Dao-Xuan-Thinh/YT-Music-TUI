import SwiftUI
import WidgetKit

/// Now Playing home-screen widget: current/last track + play state, with an
/// interactive play/pause button on iOS 17 (AudioPlaybackIntent runs in the
/// app process — audio without foregrounding). On iOS 16 the whole widget
/// deep-links into the app (ytmtui://playpause). Snapshot-driven: the app
/// writes nowplaying.json + a cached thumb into the App Group and reloads
/// this kind on track/state changes; the timeline itself never refreshes.
struct NowPlayingEntry: TimelineEntry {
    let date: Date
    let snap: NowPlayingSnapshot
    let thumb: UIImage?
    var palette: WPalette = .fallback
}

struct NowPlayingProvider: TimelineProvider {
    func placeholder(in context: Context) -> NowPlayingEntry { Self.sample }

    func getSnapshot(in context: Context, completion: @escaping (NowPlayingEntry) -> Void) {
        completion(context.isPreview ? Self.sample : Self.load())
    }

    func getTimeline(in context: Context,
                     completion: @escaping (Timeline<NowPlayingEntry>) -> Void) {
        completion(Timeline(entries: [Self.load()], policy: .never))
    }

    static func load() -> NowPlayingEntry {
        NowPlayingEntry(date: Date(), snap: NowPlayingShared.load(),
                        thumb: UIImage(contentsOfFile:
                            NowPlayingShared.thumbURL().path),
                        palette: WPalette.load())
    }

    static var sample: NowPlayingEntry {
        NowPlayingEntry(date: Date(),
                        snap: NowPlayingSnapshot(title: "Never Gonna Give You Up",
                                                 uploader: "Rick Astley",
                                                 isPlaying: true,
                                                 updated: Date()),
                        thumb: nil)
    }
}

struct NowPlayingWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "YTMusicNowPlaying",
                            provider: NowPlayingProvider()) { entry in
            NowPlayingView(entry: entry)
        }
        .configurationDisplayName("Now Playing")
        .description("The track playing in YT Music, with play/pause.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

struct NowPlayingView: View {
    @Environment(\.widgetFamily) private var family
    let entry: NowPlayingEntry
    private var p: WPalette { entry.palette }
    private var mono: (CGFloat, Font.Weight) -> Font {
        { .system(size: $0, weight: $1, design: .monospaced) }
    }

    var body: some View {
        Group {
            if !entry.snap.hasTrack {
                VStack(spacing: 6) {
                    Text("♪").font(mono(22, .regular)).foregroundStyle(p.accent)
                    Text("nothing playing yet")
                        .font(mono(11, .regular)).foregroundStyle(p.dim)
                        .multilineTextAlignment(.center)
                }
            } else if family == .systemSmall {
                smallView
            } else {
                mediumView
            }
        }
        .widgetBackground(p.bg)
        .widgetURL(URL(string: "ytmtui://playpause"))
    }

    private var art: some View {
        Group {
            if let img = entry.thumb {
                Image(uiImage: img).resizable().scaledToFill()
            } else {
                ZStack {
                    p.accent.opacity(0.15)
                    Text("♪").font(mono(20, .regular)).foregroundStyle(p.accent)
                }
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    @ViewBuilder private var playButton: some View {
        let glyph = Image(systemName: entry.snap.isPlaying ? "pause.fill" : "play.fill")
        if #available(iOSApplicationExtension 17.0, *) {
            Button(intent: TogglePlaybackIntent()) {
                glyph.font(.system(size: 16, weight: .bold))
                    .foregroundStyle(p.bg)
                    .frame(width: 34, height: 34)
                    .background(Circle().fill(p.accent))
            }
            .buttonStyle(.plain)
        } else {
            // iOS 16: static glyph — tapping anywhere opens the app via widgetURL.
            glyph.font(.system(size: 16, weight: .bold))
                .foregroundStyle(p.bg)
                .frame(width: 34, height: 34)
                .background(Circle().fill(p.accent))
        }
    }

    private var smallView: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                art.frame(width: 44, height: 44)
                Spacer()
                playButton
            }
            Spacer(minLength: 0)
            Text(entry.snap.title)
                .font(mono(12, .bold)).foregroundStyle(p.fg)
                .lineLimit(2)
            Text(entry.snap.uploader)
                .font(mono(10, .regular)).foregroundStyle(p.dim)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }

    private var mediumView: some View {
        HStack(spacing: 12) {
            art.frame(width: 92, height: 92)
            VStack(alignment: .leading, spacing: 4) {
                Text(entry.snap.isPlaying ? "▸ playing" : "‖ paused")
                    .font(mono(10, .bold)).foregroundStyle(p.accent)
                Text(entry.snap.title)
                    .font(mono(14, .bold)).foregroundStyle(p.fg)
                    .lineLimit(2)
                Text(entry.snap.uploader)
                    .font(mono(11, .regular)).foregroundStyle(p.dim)
                    .lineLimit(1)
            }
            Spacer(minLength: 4)
            playButton
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
