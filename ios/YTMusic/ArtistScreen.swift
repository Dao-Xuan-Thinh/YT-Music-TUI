import SwiftUI

/// The artist page: channel-icon header + sections (Songs / Albums / Singles / Videos).
/// Songs & videos play (as a queue); albums/singles open into the queue. Presented as a
/// full-screen cover from the artist card.
struct ArtistScreen: View {
    @ObservedObject var vm: PlayerViewModel
    @ObservedObject private var theme = ThemeManager.shared
    let page: ArtistPage

    var body: some View {
        ZStack {
            TUI.bg.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    header
                    ForEach(page.sections) { section in
                        sectionView(section)
                    }
                    Spacer(minLength: 20)
                }
                .padding(.horizontal, 16)
                .padding(.top, 10)
            }
        }
        .foregroundStyle(TUI.fg).font(TUI.mono()).tint(TUI.accent)
        .preferredColorScheme(theme.current.dark ? .dark : .light)
        // Present albums/playlists from *inside* this cover: SwiftUI can't show a
        // sibling fullScreenCover while this one is up (ContentView's collection
        // cover only fires when no artist page is open).
        .fullScreenCover(isPresented: $vm.openedCollection) {
            CollectionScreen(vm: vm, title: vm.collectionTitle, tracks: vm.collectionTracks)
        }
    }

    private var header: some View {
        HStack(spacing: 14) {
            AsyncImage(url: page.thumbnailURL) { phase in
                if case .success(let img) = phase { img.resizable().scaledToFill() }
                else { TUI.panel.overlay(Text("♪").foregroundStyle(TUI.dim)) }
            }
            .frame(width: 72, height: 72)
            .clipShape(Circle())
            .overlay(Circle().stroke(TUI.accent.opacity(0.5)))
            VStack(alignment: .leading, spacing: 3) {
                Text(page.name).font(TUI.mono(20, .bold)).foregroundStyle(TUI.accent).lineLimit(2)
                if !page.subscribers.isEmpty {
                    Text("\(page.subscribers) subscribers")
                        .font(TUI.mono(12)).foregroundStyle(TUI.dim)
                }
            }
            Spacer()
            Text("✕").font(TUI.mono(18, .bold)).foregroundStyle(TUI.dim)
                .onTapGesture { vm.closeArtist() }
        }
    }

    private func sectionView(_ section: ArtistSection) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(section.title.uppercased()).font(TUI.mono(12, .bold)).foregroundStyle(TUI.dim)
            ForEach(Array(section.items.enumerated()), id: \.element.id) { _, it in
                artistRow(it, section: section)
            }
        }
    }

    private func artistRow(_ it: SearchResult, section: ArtistSection) -> some View {
        let isOpenable = (it.kind == "album" || it.isPlaylist)
        return HStack(spacing: 10) {
            AsyncImage(url: it.thumbnailURL) { phase in
                if case .success(let img) = phase { img.resizable().scaledToFill() }
                else { TUI.panel }
            }
            .frame(width: 40, height: 40)
            .clipShape(RoundedRectangle(cornerRadius: isOpenable ? 4 : 20))
            VStack(alignment: .leading, spacing: 2) {
                Text(it.title).foregroundStyle(TUI.fg).lineLimit(1).font(TUI.mono(14))
                Text(isOpenable ? section.title.dropLast().description.lowercased()
                                : (it.uploader.isEmpty ? "song" : it.uploader))
                    .foregroundStyle(TUI.dim).lineLimit(1).font(TUI.mono(11))
            }
            Spacer(minLength: 6)
            Image(systemName: isOpenable ? "chevron.right" : "play.fill")
                .font(TUI.mono(11)).foregroundStyle(TUI.accent)
        }
        .frame(height: 46)
        .contentShape(Rectangle())
        .onTapGesture {
            if isOpenable { vm.openAlbum(id: it.playlistId ?? it.id, title: it.title) }
            else {
                // Play this section's songs as a queue, starting here.
                let songs = section.items.filter { $0.kind == "song" }
                if let start = songs.firstIndex(where: { $0.id == it.id }) {
                    vm.playList(songs, at: start)
                }
            }
        }
    }
}
