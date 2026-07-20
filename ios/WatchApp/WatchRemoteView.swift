import SwiftUI

/// The whole watch UI: what's playing on the phone + transport buttons.
/// Same TUI look as the phone app (mono, black, accent green).
struct WatchRemoteView: View {
    @ObservedObject private var link = PhoneLink.shared
    @State private var poll: Timer?

    private let accent = Color(red: 0.30, green: 0.85, blue: 0.45)
    private let dim = Color(red: 0.55, green: 0.60, blue: 0.55)

    private func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }

    var body: some View {
        VStack(spacing: 10) {
            if !link.reachable {
                Text("♪").font(mono(20)).foregroundStyle(accent)
                Text("iPhone not reachable")
                    .font(mono(12)).foregroundStyle(dim)
                    .multilineTextAlignment(.center)
            } else if link.title.isEmpty {
                Text("♪").font(mono(20)).foregroundStyle(accent)
                Text("nothing playing").font(mono(12)).foregroundStyle(dim)
            } else {
                VStack(spacing: 2) {
                    Text(link.title)
                        .font(mono(13, .bold)).foregroundStyle(.white)
                        .lineLimit(2).multilineTextAlignment(.center)
                    Text(link.artist)
                        .font(mono(11)).foregroundStyle(dim)
                        .lineLimit(1)
                }
            }
            HStack(spacing: 14) {
                button("◂◂") { link.send("prev") }
                button(link.isPlaying ? "‖" : "▸") { link.send("playpause") }
                button("▸▸") { link.send("next") }
            }
        }
        .padding(.horizontal, 6)
        .onAppear {
            link.start()
            link.refresh()
            poll = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { _ in
                link.refresh()
            }
        }
        .onDisappear { poll?.invalidate(); poll = nil }
    }

    private func button(_ glyph: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(glyph).font(mono(16, .bold)).foregroundStyle(accent)
                .frame(width: 44, height: 34)
        }
        .buttonStyle(.plain)
        .background(Color.white.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}
