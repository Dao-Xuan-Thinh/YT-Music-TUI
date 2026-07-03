import SwiftUI

/// Reusable lyrics view: follows playback on synced songs (highlight + centered
/// auto-scroll), with an on-demand translation under each line and a tappable
/// `[lang]` badge. Owns its own load triggers (on appear + on track change), so
/// hosts just embed it. Used by the full-screen player (iPhone) and the iPad
/// landscape right panel.
struct LyricsPanel: View {
    @ObservedObject var vm: PlayerViewModel
    @ObservedObject var playback: PlaybackService

    @State private var showLangPrompt = false
    @State private var langInput = ""

    var body: some View {
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
        .onAppear { loadLyricsForCurrent() }
        .onChange(of: vm.currentResult?.id) { _ in loadLyricsForCurrent() }
    }

    private func loadLyricsForCurrent() {
        if let id = vm.currentResult?.id, !id.isEmpty { vm.loadLyrics(for: id) }
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
}
