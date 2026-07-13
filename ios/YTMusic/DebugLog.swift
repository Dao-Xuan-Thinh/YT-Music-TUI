import SwiftUI

/// App-side debug log (ring buffer). The Settings debug screen shows this merged with
/// the Python engine log (`python_get_log` → resolve.get_log). Never log cookie values.
final class DebugLog: ObservableObject {
    static let shared = DebugLog()

    @Published private(set) var lines: [String] = []
    private let maxLines = 400
    private let formatter: DateFormatter

    private init() {
        formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
    }

    func log(_ tag: String, _ msg: String) {
        let line = "\(formatter.string(from: Date())) [\(tag)] \(msg)"
        NSLog("%@", line)
        DispatchQueue.main.async {
            self.lines.append(line)
            if self.lines.count > self.maxLines {
                self.lines.removeFirst(self.lines.count - self.maxLines)
            }
        }
    }
}

/// Settings → debug log: the app (Swift) log and the engine (Python) log, with copy.
struct DebugLogScreen: View {
    @ObservedObject private var dlog = DebugLog.shared
    @ObservedObject private var theme = ThemeManager.shared
    @Environment(\.dismiss) private var dismiss

    @State private var pyLog = ""
    @State private var copied = false

    var body: some View {
        ZStack {
            TUI.bg.ignoresSafeArea()
            VStack(spacing: 0) {
                header
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 14) {
                            section("APP", text: dlog.lines.isEmpty
                                    ? "(nothing logged yet)" : dlog.lines.joined(separator: "\n"))
                            section("ENGINE (yt-dlp / ytmusicapi)",
                                    text: pyLog.isEmpty ? "(nothing logged yet)" : pyLog)
                            Color.clear.frame(height: 1).id("bottom")
                        }
                        .padding(14)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .onAppear { proxy.scrollTo("bottom") }
                    .onChange(of: pyLog) { _ in proxy.scrollTo("bottom") }
                }
            }
        }
        .foregroundStyle(TUI.fg).font(TUI.mono()).tint(TUI.accent)
        .preferredColorScheme(theme.current.dark ? .dark : .light)
        .onAppear(perform: refresh)
    }

    private var header: some View {
        HStack(spacing: 16) {
            Text("debug log").font(TUI.mono(18, .bold)).foregroundStyle(TUI.accent)
            Spacer()
            Text(copied ? "copied" : "copy")
                .font(TUI.mono(14, .bold)).foregroundStyle(copied ? TUI.dim : TUI.accent)
                .onTapGesture { copyAll() }
            Text("refresh").font(TUI.mono(14, .bold)).foregroundStyle(TUI.accent)
                .onTapGesture { refresh() }
            Text("done").font(TUI.mono(14, .bold)).foregroundStyle(TUI.accent)
                .onTapGesture { dismiss() }
        }
        .padding(14).background(TUI.panel)
    }

    private func section(_ title: String, text: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(TUI.mono(11, .bold)).foregroundStyle(TUI.dim)
            Text(text)
                .font(TUI.mono(11))
                .foregroundStyle(TUI.fg.opacity(0.9))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func refresh() {
        DispatchQueue.global(qos: .userInitiated).async {
            let c = python_get_log()
            let s = c.map { String(cString: $0) } ?? ""
            if let c { free(c) }
            DispatchQueue.main.async { pyLog = s }
        }
    }

    private func copyAll() {
        UIPasteboard.general.string =
            "== APP ==\n" + dlog.lines.joined(separator: "\n") +
            "\n\n== ENGINE ==\n" + pyLog
        copied = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { copied = false }
    }
}
