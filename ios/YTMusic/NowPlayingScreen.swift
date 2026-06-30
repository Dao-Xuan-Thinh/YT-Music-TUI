import SwiftUI

/// Full-screen "now playing": large artwork, scrubber, transport, shuffle/repeat/like,
/// volume. Presented from the mini bar; swipe down (or ▾) to dismiss. Keeps the Hybrid-TUI
/// monospace/green look.
struct NowPlayingScreen: View {
    @ObservedObject var vm: PlayerViewModel
    @ObservedObject var playback: PlaybackService
    @ObservedObject private var library = LibraryStore.shared
    @ObservedObject private var theme = ThemeManager.shared
    @Environment(\.dismiss) private var dismiss

    @State private var scrub: Double = 0
    @State private var scrubbing = false
    @State private var dragY: CGFloat = 0

    var body: some View {
        ZStack {
            TUI.bg.ignoresSafeArea()
            VStack(spacing: 18) {
                grabber
                artwork
                trackInfo
                scrubber
                transport
                toggles
                volume
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 24)
            .padding(.top, 8)
        }
        .foregroundStyle(TUI.fg)
        .font(TUI.mono())
        .tint(TUI.accent)
        .preferredColorScheme(.dark)
        .offset(y: max(dragY, 0))
        .gesture(
            DragGesture()
                .onChanged { v in if v.translation.height > 0 { dragY = v.translation.height } }
                .onEnded { v in
                    if v.translation.height > 120 { dismiss() } else { dragY = 0 }
                }
        )
        .onChange(of: playback.position) { p in if !scrubbing { scrub = p } }
        .onAppear { scrub = playback.position }
    }

    // MARK: - Pieces

    private var grabber: some View {
        VStack(spacing: 10) {
            Capsule().fill(TUI.dim.opacity(0.5)).frame(width: 38, height: 5)
            HStack {
                Text("▾ now playing").font(TUI.mono(12, .bold)).foregroundStyle(TUI.dim)
                    .onTapGesture { dismiss() }
                Spacer()
                let i = (vm.queueIndex ?? -1) + 1
                Text("q \(i)/\(vm.queue.count)").font(TUI.mono(12)).foregroundStyle(TUI.dim)
            }
        }
    }

    private var artwork: some View {
        AsyncImage(url: playback.current?.thumbnailURL) { phase in
            if case .success(let img) = phase { img.resizable().scaledToFill() }
            else { TUI.panel.overlay(Text("♪").font(.system(size: 64)).foregroundStyle(TUI.dim)) }
        }
        .aspectRatio(1, contentMode: .fit)
        .frame(maxWidth: .infinity)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(TUI.dim.opacity(0.3)))
        .padding(.horizontal, 8)
    }

    private var trackInfo: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                WaveText(text: playback.current?.title ?? "nothing playing",
                         palette: theme.current.wave,
                         font: TUI.mono(18, .bold),
                         fallback: TUI.fg,
                         active: playback.isPlaying && playback.current != nil,
                         lineLimit: 2)
                Text(playback.current?.uploader ?? " ")
                    .font(TUI.mono(13)).foregroundStyle(TUI.dim).lineLimit(1)
            }
            Spacer(minLength: 8)
            Button { vm.toggleLikeCurrent() } label: {
                Image(systemName: likedNow ? "heart.fill" : "heart").font(.title2)
            }
            .foregroundStyle(TUI.accent)
            .disabled(vm.currentResult == nil)
        }
    }

    private var scrubber: some View {
        VStack(spacing: 4) {
            Slider(value: $scrub, in: 0...max(playback.duration, 1)) { ed in
                scrubbing = ed
                if !ed { playback.seek(to: scrub) }
            }
            .disabled(playback.current == nil)
            HStack {
                Text(timeString(scrub)).font(TUI.mono(11)).foregroundStyle(TUI.dim)
                Spacer()
                Text(timeString(playback.duration)).font(TUI.mono(11)).foregroundStyle(TUI.dim)
            }
        }
    }

    private var transport: some View {
        HStack(spacing: 44) {
            Button { vm.playPrevious() } label: { Image(systemName: "backward.end.fill").font(.title) }
            Button { playback.togglePlayPause() } label: {
                Image(systemName: playback.isPlaying ? "pause.circle.fill" : "play.circle.fill")
                    .font(.system(size: 64))
            }
            Button { vm.playNext() } label: { Image(systemName: "forward.end.fill").font(.title) }
        }
        .foregroundStyle(TUI.accent)
        .disabled(playback.current == nil)
    }

    private var toggles: some View {
        HStack(spacing: 40) {
            Text("shuffle")
                .foregroundStyle(vm.shuffle ? TUI.accent : TUI.dim)
                .onTapGesture { vm.toggleShuffle() }
            Text("repeat:\(vm.repeatMode.rawValue)")
                .foregroundStyle(vm.repeatMode == .off ? TUI.dim : TUI.accent)
                .onTapGesture { vm.cycleRepeat() }
        }
        .font(TUI.mono(13, .bold))
    }

    private var volume: some View {
        HStack(spacing: 10) {
            Image(systemName: "speaker.fill").font(.caption).foregroundStyle(TUI.dim)
            Slider(value: $playback.volume, in: 0...1)
            Image(systemName: "speaker.wave.3.fill").font(.caption).foregroundStyle(TUI.dim)
            Text("\(Int(playback.volume * 100))%").font(TUI.mono(11)).foregroundStyle(TUI.dim)
                .frame(width: 38, alignment: .trailing)
        }
        .padding(.top, 4)
    }

    private var likedNow: Bool {
        guard let r = vm.currentResult else { return false }
        return library.isLiked(r.id)
    }

    private func timeString(_ s: Double) -> String {
        guard s.isFinite, s >= 0 else { return "0:00" }
        let t = Int(s)
        return String(format: "%d:%02d", t / 60, t % 60)
    }
}
