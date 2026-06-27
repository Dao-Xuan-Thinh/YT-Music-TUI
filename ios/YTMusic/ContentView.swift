import SwiftUI

struct ContentView: View {
    @StateObject private var vm = PlayerViewModel()
    @ObservedObject private var playback = PlaybackService.shared

    @State private var query = ""
    @FocusState private var searchFocused: Bool

    @State private var scrub: Double = 0
    @State private var scrubbing = false
    @State private var dragStartHighlight: Int?
    @State private var navMode = false   // true while long-press-drag owns the list

    private let rowHeight: CGFloat = 30

    var body: some View {
        ZStack {
            TUI.bg.ignoresSafeArea()
            VStack(spacing: 8) {
                tabBar
                if vm.tab == .search { searchRow }
                TUIDivider()
                list
                TUIDivider()
                nowPlaying
                footer
            }
            .padding(.horizontal, 12)
            .padding(.top, 6)
        }
        .foregroundStyle(TUI.fg)
        .font(TUI.mono())
        .tint(TUI.accent)
        .preferredColorScheme(.dark)
        .onChange(of: playback.position) { p in if !scrubbing { scrub = p } }
    }

    // MARK: - Tab bar

    private var tabBar: some View {
        HStack(spacing: 14) {
            tabLabel("SEARCH", .search)
            tabLabel("QUEUE", .queue)
            Spacer()
            Text("♥ —").foregroundStyle(TUI.dim)
        }
        .font(TUI.mono(14, .bold))
    }

    private func tabLabel(_ title: String, _ t: Tab) -> some View {
        let active = vm.tab == t
        return Text(active ? "[ \(title) ]" : title.lowercased())
            .foregroundStyle(active ? TUI.accent : TUI.dim)
            .onTapGesture { vm.tab = t }
    }

    // MARK: - Search

    private var searchRow: some View {
        HStack(spacing: 6) {
            Text("/").foregroundStyle(TUI.accent)
            TextField("", text: $query,
                      prompt: Text("search or paste url").foregroundColor(TUI.dim))
                .focused($searchFocused)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.search)
                .onSubmit { vm.submit(query); searchFocused = false }
            if vm.searching || vm.resolving {
                ProgressView().controlSize(.small).tint(TUI.accent)
            }
            Text("src:\(vm.source.rawValue)")
                .font(TUI.mono(12))
                .foregroundStyle(TUI.accent)
                .onTapGesture { vm.cycleSource() }
        }
        .padding(8)
        .background(TUI.panel)
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(TUI.dim.opacity(0.4)))
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    // MARK: - Results / queue list (shared) with gesture navigation

    private var list: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    if let e = vm.errorMsg, vm.displayed.isEmpty {
                        Text(e).foregroundStyle(TUI.warn).padding(.vertical, 8)
                    }
                    ForEach(Array(vm.displayed.enumerated()), id: \.element.id) { idx, r in
                        row(idx, r)
                    }
                }
            }
            .scrollDisabled(navMode)
            .simultaneousGesture(highlightDrag)
            .onChange(of: vm.highlightIndex) { i in
                guard vm.displayed.indices.contains(i) else { return }
                withAnimation(.easeOut(duration: 0.1)) {
                    proxy.scrollTo(vm.displayed[i].id, anchor: .center)
                }
            }
        }
        .frame(maxHeight: .infinity)
    }

    private func row(_ idx: Int, _ r: SearchResult) -> some View {
        let playing = (r.id == vm.playingID)
        let highlighted = (idx == vm.highlightIndex)
        return HStack(spacing: 8) {
            Text(playing ? "▸" : (highlighted ? "›" : " ")).foregroundStyle(TUI.accent)
            Text(String(format: "%2d", idx + 1)).foregroundStyle(TUI.dim)
            Text(r.title)
                .foregroundStyle(playing ? TUI.accent : TUI.fg)
                .lineLimit(1).truncationMode(.tail)
            Spacer(minLength: 6)
            Text(timeString(Double(r.duration))).foregroundStyle(TUI.dim)
        }
        .font(TUI.mono(13))
        .frame(height: rowHeight)
        .background(highlighted ? TUI.accent.opacity(0.12) : .clear)
        .contentShape(Rectangle())
        .onTapGesture(count: 2) { vm.tab = (vm.tab == .search ? .queue : .search) }
        .onTapGesture { playRow(idx) }
    }

    private func playRow(_ idx: Int) {
        vm.tab == .search ? vm.playFromResults(at: idx) : vm.playFromQueue(at: idx)
    }

    /// Long-press-then-drag moves the highlighter; scrolling is suspended while it's active
    /// so the two don't fight.
    private var highlightDrag: some Gesture {
        LongPressGesture(minimumDuration: 0.25)
            .sequenced(before: DragGesture(minimumDistance: 0))
            .onChanged { value in
                if case .second(true, let drag?) = value {
                    navMode = true
                    if dragStartHighlight == nil { dragStartHighlight = vm.highlightIndex }
                    let delta = Int((drag.translation.height / rowHeight).rounded())
                    vm.highlightIndex = min(max((dragStartHighlight ?? 0) + delta, 0),
                                            max(vm.displayed.count - 1, 0))
                }
            }
            .onEnded { _ in dragStartHighlight = nil; navMode = false }
    }

    // MARK: - Now playing

    private var nowPlaying: some View {
        VStack(spacing: 6) {
            HStack(spacing: 10) {
                AsyncImage(url: playback.current?.thumbnailURL) { phase in
                    if case .success(let img) = phase { img.resizable().scaledToFill() }
                    else { TUI.panel }
                }
                .frame(width: 48, height: 48)
                .clipShape(RoundedRectangle(cornerRadius: 4))
                VStack(alignment: .leading, spacing: 2) {
                    Text(playback.current?.title ?? "nothing playing")
                        .font(TUI.mono(14, .bold)).lineLimit(1)
                    Text(playback.current?.uploader ?? " ")
                        .font(TUI.mono(12)).foregroundStyle(TUI.dim).lineLimit(1)
                }
                Spacer()
            }

            Slider(value: $scrub, in: 0...max(playback.duration, 1), onEditingChanged: { ed in
                scrubbing = ed
                if !ed { playback.seek(to: scrub) }
            })
            .disabled(playback.current == nil)

            HStack {
                Text(timeString(scrub)).font(TUI.mono(11)).foregroundStyle(TUI.dim)
                Spacer()
                Text(timeString(playback.duration)).font(TUI.mono(11)).foregroundStyle(TUI.dim)
            }

            HStack(spacing: 48) {
                Button { vm.playPrevious() } label: { Image(systemName: "backward.end.fill").font(.title2) }
                Button { playback.togglePlayPause() } label: {
                    Image(systemName: playback.isPlaying ? "pause.fill" : "play.fill").font(.largeTitle)
                }
                Button { vm.playNext() } label: { Image(systemName: "forward.end.fill").font(.title2) }
            }
            .foregroundStyle(TUI.accent)
            .disabled(playback.current == nil)
            .padding(.top, 2)
        }
    }

    // MARK: - Footer

    private var footer: some View {
        let i = (vm.queueIndex ?? -1) + 1
        return HStack(spacing: 6) {
            Text(vm.source.rawValue).foregroundStyle(TUI.dim).onTapGesture { vm.cycleSource() }
            sep
            Text("shuf:\(vm.shuffle ? "on" : "off")")
                .foregroundStyle(vm.shuffle ? TUI.accent : TUI.dim)
                .onTapGesture { vm.toggleShuffle() }
            sep
            Text("rep:\(vm.repeatMode.rawValue)")
                .foregroundStyle(vm.repeatMode == .off ? TUI.dim : TUI.accent)
                .onTapGesture { vm.cycleRepeat() }
            sep
            Text("q:\(i)/\(vm.queue.count)").foregroundStyle(TUI.dim)
            sep
            Text("\(Int(playback.volume * 100))%").foregroundStyle(TUI.dim)
            Spacer()
        }
        .font(TUI.mono(11))
        .padding(.vertical, 4)
    }

    private var sep: some View { Text("·").foregroundStyle(TUI.dim.opacity(0.6)) }

    private func timeString(_ s: Double) -> String {
        guard s.isFinite, s >= 0 else { return "0:00" }
        let t = Int(s)
        return String(format: "%d:%02d", t / 60, t % 60)
    }
}
