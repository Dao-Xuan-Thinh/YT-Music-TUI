import SwiftUI

/// The seek slider + elapsed/total labels, shared by the full-screen player and the
/// landscape bar (they had identical copies of this, and of the bug below).
///
/// **The displayed position is `playback.position` — never a mirror of it.** The previous
/// version drove the slider from a `@State scrub` that was fed only by
/// `.onChange(of: playback.position) { if !scrubbing { scrub = p } }`, so the whole bar
/// froze at 0:00 the moment `scrubbing` latched true (an `onEditingChanged(true)` with no
/// matching `false`) or that `onChange` stopped firing. Audio, listen-stats and the
/// lock-screen bar all kept working, because none of them read the mirror — which is
/// precisely how the bug presented. Reading the published value straight from the body
/// re-renders on every tick with no intermediary to get stuck.
///
/// `scrub` now exists only for the duration of a drag, and even that self-heals: if the
/// end-of-drag callback never arrives, the stale-scrub check below hands control back.
struct ScrubBar: View {
    @ObservedObject var playback: PlaybackService
    /// Labels are omitted on the compact landscape bar, where there's no room.
    var showLabels: Bool = true

    @State private var scrub: Double = 0
    @State private var scrubbing = false
    @State private var lastScrubAt = Date.distantPast

    /// How long a drag may sit motionless before we assume its end callback was lost.
    private static let scrubTimeout: TimeInterval = 1.5

    private var shown: Double { scrubbing ? scrub : playback.position }

    var body: some View {
        VStack(spacing: 4) {
            Slider(
                value: Binding(
                    get: { shown },
                    set: { v in
                        scrub = v
                        scrubbing = true       // a value change *is* a drag in progress
                        lastScrubAt = Date()
                    }
                ),
                in: 0...max(playback.duration, 1),
                onEditingChanged: { editing in
                    if editing {
                        scrubbing = true
                        lastScrubAt = Date()
                    } else {
                        scrubbing = false
                        playback.seek(to: scrub)
                    }
                }
            )
            .disabled(playback.current == nil)

            if showLabels {
                HStack {
                    Text(timeString(shown)).font(TUI.mono(11)).foregroundStyle(TUI.dim)
                    Spacer()
                    Text(timeString(playback.duration)).font(TUI.mono(11)).foregroundStyle(TUI.dim)
                }
            }
        }
        // Safety net: a drag that goes quiet for scrubTimeout is treated as finished, so a
        // missing end-of-drag callback can never strand the bar again.
        .onChange(of: playback.position) { _ in
            if scrubbing, Date().timeIntervalSince(lastScrubAt) > Self.scrubTimeout {
                scrubbing = false
            }
        }
        // A new track always cancels any in-flight scrub state.
        .onChange(of: playback.current?.id) { _ in
            scrubbing = false
            scrub = 0
        }
    }

    private func timeString(_ s: Double) -> String {
        guard s.isFinite, s >= 0 else { return "0:00" }
        let t = Int(s)
        return String(format: "%d:%02d", t / 60, t % 60)
    }
}
