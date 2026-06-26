import SwiftUI

struct ContentView: View {
    @State private var status = "Tap Resolve to extract a track via embedded yt-dlp"
    @State private var busy = false

    var body: some View {
        VStack(spacing: 16) {
            Text("YT Music — extraction spike")
                .font(.headline)
            ScrollView {
                Text(status)
                    .font(.system(.footnote, design: .monospaced))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
            }
            .frame(maxHeight: 360)
            Button(busy ? "Resolving…" : "Resolve test track") {
                resolve()
            }
            .buttonStyle(.borderedProminent)
            .disabled(busy)
        }
        .padding()
        .onAppear { resolve() }   // auto-run so logs show the result without interaction
    }

    private func resolve() {
        busy = true
        status = "Resolving…"
        DispatchQueue.global(qos: .userInitiated).async {
            let url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            let cstr = python_resolve(url)
            let json = String(cString: cstr!)
            free(cstr)
            NSLog("RESOLVE_RESULT: %@", json)
            DispatchQueue.main.async {
                status = pretty(json)
                busy = false
            }
        }
    }

    private func pretty(_ json: String) -> String {
        guard let data = json.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data),
              let out = try? JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys]),
              let s = String(data: out, encoding: .utf8) else { return json }
        return s
    }
}
