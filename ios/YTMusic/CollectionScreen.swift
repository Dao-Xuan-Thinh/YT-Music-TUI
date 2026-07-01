import SwiftUI

/// A "view first" track list for a playlist or album (For You / Artist page). Shows a back
/// button, the title, a ▶ play-all, and the tracks — tapping a track plays the collection
/// from there. Presented full-screen; the VM owns the loaded tracks (`openedCollection`).
struct CollectionScreen: View {
    @ObservedObject var vm: PlayerViewModel
    @ObservedObject private var theme = ThemeManager.shared
    let title: String
    let tracks: [SearchResult]

    var body: some View {
        ZStack {
            TUI.bg.ignoresSafeArea()
            VStack(spacing: 8) {
                HStack(spacing: 10) {
                    Text("‹ back").foregroundStyle(TUI.accent)
                        .onTapGesture { vm.closeCollection() }
                    Spacer(minLength: 6)
                    Text(title).foregroundStyle(TUI.dim).lineLimit(1)
                    Spacer(minLength: 6)
                    Text("▶ play all").foregroundStyle(TUI.accent)
                        .onTapGesture { vm.playCollection() }
                }
                .font(TUI.mono(13, .bold))
                TUIDivider()
                if vm.collectionLoading {
                    HStack { Spacer(); ProgressView().tint(TUI.accent); Spacer() }.padding(.vertical, 24)
                } else if tracks.isEmpty {
                    Text("empty").foregroundStyle(TUI.dim).padding(.vertical, 12)
                }
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(tracks.enumerated()), id: \.element.id) { idx, r in
                            row(idx, r)
                        }
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 14).padding(.top, 10)
        }
        .foregroundStyle(TUI.fg).font(TUI.mono()).tint(TUI.accent)
        .preferredColorScheme(theme.current.dark ? .dark : .light)
    }

    private func row(_ idx: Int, _ r: SearchResult) -> some View {
        HStack(spacing: 8) {
            Text(String(format: "%2d", idx + 1)).foregroundStyle(TUI.dim)
            Text(r.title).foregroundStyle(TUI.fg).lineLimit(1).truncationMode(.tail)
            Spacer(minLength: 6)
            Text(r.duration > 0 ? timeString(r.duration) : "").foregroundStyle(TUI.dim)
        }
        .font(TUI.mono(13)).frame(height: 32).contentShape(Rectangle())
        .onTapGesture { vm.playCollection(at: idx) }
    }

    private func timeString(_ s: Int) -> String { String(format: "%d:%02d", s / 60, s % 60) }
}
