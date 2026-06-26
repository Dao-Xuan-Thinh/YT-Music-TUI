import SwiftUI

struct ContentView: View {
    @ObservedObject private var playback = PlaybackService.shared

    @State private var urlText = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    @State private var resolving = false
    @State private var errorMsg: String?

    // Scrubber state (decoupled from live position while dragging).
    @State private var scrub: Double = 0
    @State private var scrubbing = false

    var body: some View {
        VStack(spacing: 20) {
            Text("YT Music")
                .font(.title2).bold()

            HStack {
                TextField("YouTube URL or video id", text: $urlText)
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                Button(resolving ? "…" : "Play") { resolveAndPlay() }
                    .buttonStyle(.borderedProminent)
                    .disabled(resolving)
            }

            if let e = errorMsg {
                Text(e).font(.footnote).foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }

            artwork

            VStack(spacing: 4) {
                Text(playback.current?.title ?? "Nothing playing")
                    .font(.headline).lineLimit(2).multilineTextAlignment(.center)
                Text(playback.current?.uploader ?? " ")
                    .font(.subheadline).foregroundStyle(.secondary)
            }

            scrubber

            HStack(spacing: 40) {
                Button { playback.skip(-15) } label: {
                    Image(systemName: "gobackward.15").font(.title)
                }
                Button { playback.togglePlayPause() } label: {
                    Image(systemName: playback.isPlaying ? "pause.circle.fill" : "play.circle.fill")
                        .font(.system(size: 64))
                }
                Button { playback.skip(15) } label: {
                    Image(systemName: "goforward.15").font(.title)
                }
            }
            .disabled(playback.current == nil)

            Spacer()
        }
        .padding()
        .onChange(of: playback.position) { newPos in
            if !scrubbing { scrub = newPos }
        }
    }

    private var artwork: some View {
        AsyncImage(url: playback.current?.thumbnailURL) { phase in
            switch phase {
            case .success(let img): img.resizable().scaledToFill()
            default: Color.secondary.opacity(0.15)
            }
        }
        .frame(width: 240, height: 240)
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .overlay { if resolving { ProgressView() } }
    }

    private var scrubber: some View {
        let dur = max(playback.duration, 1)
        return VStack(spacing: 2) {
            Slider(value: $scrub, in: 0...dur, onEditingChanged: { editing in
                scrubbing = editing
                if !editing { playback.seek(to: scrub) }
            })
            .disabled(playback.current == nil)
            HStack {
                Text(timeString(scrub)).font(.caption).monospacedDigit()
                Spacer()
                Text(timeString(playback.duration)).font(.caption).monospacedDigit()
            }
            .foregroundStyle(.secondary)
        }
    }

    private func resolveAndPlay() {
        resolving = true
        errorMsg = nil
        let input = urlText
        DispatchQueue.global(qos: .userInitiated).async {
            let cstr = python_resolve(input)
            let json = cstr.map { String(cString: $0) } ?? "{}"
            if let p = cstr { free(p) }
            NSLog("RESOLVE_RESULT: %@", json)
            let track = Track.decode(json)
            DispatchQueue.main.async {
                resolving = false
                if let t = track, t.ok, t.streamAVURL != nil {
                    playback.play(t)
                } else {
                    errorMsg = track?.error ?? "Could not resolve a playable stream"
                }
            }
        }
    }

    private func timeString(_ s: Double) -> String {
        guard s.isFinite, s >= 0 else { return "0:00" }
        let t = Int(s)
        return String(format: "%d:%02d", t / 60, t % 60)
    }
}
