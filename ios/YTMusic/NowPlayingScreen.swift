import SwiftUI

/// Full-screen "now playing" — a "terminal boombox": ASCII-framed artwork beside a live
/// block-char equalizer, a color-wave title, and monospace transport. Swipe down (or ▾) to
/// dismiss. The equalizer is decorative (AVPlayer exposes no FFT) — it animates while
/// playing and settles flat when paused.
struct NowPlayingScreen: View {
    @ObservedObject var vm: PlayerViewModel
    @ObservedObject var playback: PlaybackService
    @ObservedObject private var library = LibraryStore.shared
    @ObservedObject private var theme = ThemeManager.shared
    @Environment(\.dismiss) private var dismiss
    @Environment(\.horizontalSizeClass) private var hSize

    /// Artwork/equalizer edge: larger in regular width (iPad) than on iPhone.
    private var artSize: CGFloat { hSize == .regular ? 200 : 128 }

    @State private var scrub: Double = 0
    @State private var scrubbing = false
    @State private var dragY: CGFloat = 0
    @State private var showLangPrompt = false
    @State private var langInput = ""

    var body: some View {
        ZStack {
            TUI.bg.ignoresSafeArea()
            VStack(spacing: 16) {
                grabber
                boombox
                trackInfo
                scrubber
                transport
                toggles
                volume
                lyricsSection
            }
            .padding(.horizontal, 22)
            .padding(.top, 8)
            .frame(maxWidth: 640)   // readable column on iPad; no effect on iPhone
        }
        .foregroundStyle(TUI.fg)
        .font(TUI.mono())
        .tint(TUI.accent)
        .preferredColorScheme(theme.current.dark ? .dark : .light)
        .offset(y: max(dragY, 0))
        .gesture(
            DragGesture()
                .onChanged { v in if v.translation.height > 0 { dragY = v.translation.height } }
                .onEnded { v in if v.translation.height > 120 { dismiss() } else { dragY = 0 } }
        )
        .onChange(of: playback.position) { p in if !scrubbing { scrub = p } }
        .onAppear { scrub = playback.position; loadLyricsForCurrent() }
        .onChange(of: vm.currentResult?.id) { _ in loadLyricsForCurrent() }
    }

    private func loadLyricsForCurrent() {
        if let id = vm.currentResult?.id, !id.isEmpty { vm.loadLyrics(for: id) }
    }

    /// Lyrics at the bottom of the player: follows playback (highlights + auto-scrolls the
    /// current line on synced songs), with an on-demand translation under each line.
    private var lyricsSection: some View {
        let cur = vm.currentLyricIndex(positionSeconds: playback.position)
        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Text("lyrics").font(TUI.mono(11, .bold)).foregroundStyle(TUI.dim)
                if vm.lyricsLoading || vm.translating {
                    ProgressView().controlSize(.mini).tint(TUI.accent)
                }
                Spacer()
                if vm.lyricsAvailable {
                    Text(vm.translateOn ? "translated" : "translate")
                        .font(TUI.mono(11, .bold))
                        .foregroundStyle(vm.translateOn ? TUI.accent : TUI.dim)
                        .onTapGesture { vm.toggleTranslate() }
                    Text("[\(vm.translateLang)]").font(TUI.mono(11)).foregroundStyle(TUI.dim)
                        .onTapGesture { langInput = vm.translateLang; showLangPrompt = true }
                }
            }
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 3) {
                        if vm.lyricsAvailable {
                            ForEach(Array(vm.lyricLines.enumerated()), id: \.offset) { i, ln in
                                lyricRow(i, ln, current: i == cur)
                            }
                        } else if !vm.lyricsLoading {
                            Text("no lyrics for this track")
                                .font(TUI.mono(12)).foregroundStyle(TUI.dim)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .onChange(of: cur) { i in
                    guard vm.lyricsSynced, i >= 0 else { return }
                    withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo(i, anchor: .center) }
                }
            }
            .frame(maxHeight: .infinity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .alert("Translate to", isPresented: $showLangPrompt) {
            TextField("language code (en, vi, ja…)", text: $langInput)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
            Button("Set") { vm.setTranslateLang(langInput) }
            Button("Cancel", role: .cancel) {}
        }
    }

    @ViewBuilder private func lyricRow(_ i: Int, _ ln: LyricLine, current: Bool) -> some View {
        let played = vm.lyricsSynced && i < vm.currentLyricIndex(positionSeconds: playback.position)
        VStack(alignment: .leading, spacing: 1) {
            Text(ln.text.isEmpty ? " " : ln.text)
                .font(TUI.mono(current ? 14 : 13, current ? .bold : .regular))
                .foregroundStyle(current ? TUI.accent : (played ? TUI.dim : TUI.fg))
            if vm.translateOn, i < vm.lyricsTranslated.count {
                let tr = vm.lyricsTranslated[i]
                if !tr.isEmpty && tr != ln.text {
                    Text(tr).font(TUI.mono(11)).italic().foregroundStyle(TUI.dim)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .id(i)
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

    /// The boombox panel: ┌─[ ♪ NOW PLAYING ]─┐ frame around square art + the equalizer.
    private var boombox: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("┌─[ ♪ NOW PLAYING ]" + String(repeating: "─", count: 120) + "┐")
                .lineLimit(1).clipped()
                .foregroundStyle(TUI.accent).font(TUI.mono(12))
            HStack(spacing: 14) {
                Text("│").foregroundStyle(TUI.accent).font(TUI.mono(12))
                AsyncImage(url: playback.current?.thumbnailURL) { phase in
                    if case .success(let img) = phase { img.resizable().scaledToFill() }
                    else { TUI.panel.overlay(Text("♪").font(.system(size: 40)).foregroundStyle(TUI.dim)) }
                }
                .frame(width: artSize, height: artSize)
                .clipShape(RoundedRectangle(cornerRadius: 4))
                Equalizer(playback: playback, active: playback.isPlaying,
                          palette: theme.current.wave ?? [TUI.accent])
                    .frame(maxWidth: .infinity, minHeight: artSize, maxHeight: artSize)
                Text("│").foregroundStyle(TUI.accent).font(TUI.mono(12))
            }
            .padding(.vertical, 10)
            Text("└" + String(repeating: "─", count: 120) + "┘")
                .lineLimit(1).clipped()
                .foregroundStyle(TUI.accent).font(TUI.mono(12))
        }
    }

    private var trackInfo: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                WaveText(text: playback.current?.title ?? "nothing playing",
                         palette: theme.current.wave, font: TUI.mono(18, .bold),
                         fallback: TUI.fg,
                         active: playback.isPlaying && playback.current != nil, lineLimit: 2)
                let artist = playback.current?.uploader ?? " "
                Text(artist)
                    .font(TUI.mono(13)).foregroundStyle(TUI.dim).lineLimit(1)
                    .contentShape(Rectangle())
                    .onTapGesture {
                        guard !artist.trimmingCharacters(in: .whitespaces).isEmpty else { return }
                        dismiss()                       // close the player first
                        vm.openArtistByName(artist)     // then present the artist page
                    }
            }
            Spacer(minLength: 8)
            Button { vm.toggleLikeCurrent() } label: {
                Image(systemName: likedNow ? "heart.fill" : "heart").font(.title2)
            }
            .foregroundStyle(TUI.accent).disabled(vm.currentResult == nil)
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
        HStack(spacing: 18) {
            boxButton("◀◀") { vm.playPrevious() }
            boxButton(playback.isPlaying ? "❚❚ PAUSE" : "▶ PLAY", wide: true) {
                playback.togglePlayPause()
            }
            boxButton("▶▶") { vm.playNext() }
        }
        .disabled(playback.current == nil)
    }

    private func boxButton(_ label: String, wide: Bool = false, _ action: @escaping () -> Void) -> some View {
        Text("[ \(label) ]")
            .font(TUI.mono(wide ? 16 : 14, .bold))
            .foregroundStyle(TUI.accent)
            .frame(maxWidth: wide ? .infinity : nil)
            .padding(.vertical, 8)
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(TUI.accent.opacity(0.5)))
            .contentShape(Rectangle())
            .onTapGesture(perform: action)
    }

    private var toggles: some View {
        HStack(spacing: 30) {
            Text("shuffle")
                .foregroundStyle(vm.shuffle ? TUI.accent : TUI.dim)
                .onTapGesture { vm.toggleShuffle() }
            Text("repeat:\(vm.repeatMode.rawValue)")
                .foregroundStyle(vm.repeatMode == .off ? TUI.dim : TUI.accent)
                .onTapGesture { vm.cycleRepeat() }
            Text("∞ radio")
                .foregroundStyle(vm.currentResult == nil ? TUI.dim : TUI.accent)
                .onTapGesture { vm.startRadio() }
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

/// A block-char spectrum. Prefers the **real** audio levels from the MTAudioProcessingTap
/// (`playback.audioLevels`); when those aren't feeding (paused, or a stream where the tap
/// doesn't fire) it falls back to a decorative per-bar sine mix. Colored from the theme wave.
private struct Equalizer: View {
    @ObservedObject var playback: PlaybackService
    let active: Bool
    let palette: [Color]
    private let bars = 16
    private let glyphs = Array("▁▂▃▄▅▆▇█")

    var body: some View {
        TimelineView(.periodic(from: .now, by: active ? 0.06 : 0.5)) { tl in
            let t = tl.date.timeIntervalSinceReferenceDate
            let real = playback.audioLevels            // [] when stale/not feeding
            HStack(alignment: .bottom, spacing: 3) {
                ForEach(0..<bars, id: \.self) { i in
                    Text(String(glyph(i, t, real)))
                        .font(TUI.mono(22))
                        .foregroundStyle(palette[i % palette.count])
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func glyph(_ i: Int, _ t: Double, _ real: [Float]) -> Character {
        guard active else { return glyphs[0] }
        let n: Double
        if real.count == bars {
            n = Double(real[i])                        // real audio level
        } else {
            // Decorative fallback: a few sines at different rates/phases per bar.
            let x = Double(i)
            let v = sin(t * 6 + x * 0.7) * 0.5 + sin(t * 3.3 + x * 1.9) * 0.3
                  + sin(t * 9.1 + x * 0.4) * 0.2
            n = (v + 1) / 2
        }
        let idx = min(glyphs.count - 1, max(0, Int(n * Double(glyphs.count))))
        return glyphs[idx]
    }
}
