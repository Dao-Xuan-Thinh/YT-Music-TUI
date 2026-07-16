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

/// One parsed log line: "HH:mm:ss [tag] message" (both the Swift and Python
/// logs use this shape). Anything unparsable renders as a plain message.
private struct LogLine: Identifiable {
    let id: Int
    let time: String
    let tag: String
    let msg: String

    init(_ raw: String, id: Int) {
        self.id = id
        if let lb = raw.firstIndex(of: "["), let rb = raw.firstIndex(of: "]"),
           lb < rb {
            time = String(raw[..<lb]).trimmingCharacters(in: .whitespaces)
            tag = String(raw[raw.index(after: lb)..<rb])
            msg = String(raw[raw.index(after: rb)...]).trimmingCharacters(in: .whitespaces)
        } else {
            time = ""; tag = ""; msg = raw
        }
    }

    /// Fixed hues for the tags that matter; anything else gets a stable hashed hue.
    var tagColor: Color {
        switch tag {
        case "resolve":  return TUI.accent
        case "playback": return Color(hue: 0.08, saturation: 0.75, brightness: 0.95) // orange
        case "auth":     return Color(hue: 0.52, saturation: 0.65, brightness: 0.90) // cyan
        case "stats":    return Color(hue: 0.36, saturation: 0.65, brightness: 0.85) // green
        case "update":   return Color(hue: 0.78, saturation: 0.55, brightness: 0.95) // violet
        case "":         return TUI.dim
        default:
            let h = Double(abs(tag.hashValue % 360)) / 360.0
            return Color(hue: h, saturation: 0.55, brightness: 0.90)
        }
    }

    var isBad: Bool {
        let low = msg.lowercased()
        return ["failed", "error", "403", "dead", "unavailable", "stall",
                "expired", "rejected", "skipping", "stopping"].contains { low.contains($0) }
    }

    var isGood: Bool {
        let low = msg.lowercased()
        return ["ok=true", "synced", "signed in", "replaced ", "ok in "].contains { low.contains($0) }
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
                        LazyVStack(alignment: .leading, spacing: 14) {
                            section("APP", lines: dlog.lines)
                            section("ENGINE · yt-dlp / ytmusicapi",
                                    lines: pyLog.isEmpty ? []
                                        : pyLog.components(separatedBy: "\n"))
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

    /// Section = a `── TITLE ────` divider + zebra-striped, syntax-colored rows.
    private func section(_ title: String, lines: [String]) -> some View {
        let parsed = lines.filter { !$0.isEmpty }
                          .enumerated().map { LogLine($1, id: $0) }
        return VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 6) {
                Text("──").foregroundStyle(TUI.dim)
                Text(title).font(TUI.mono(11, .bold)).foregroundStyle(TUI.accent)
                Rectangle().fill(TUI.dim.opacity(0.4)).frame(height: 1)
            }
            .font(TUI.mono(11))
            .padding(.bottom, 6)
            if parsed.isEmpty {
                Text("(nothing logged yet)").font(TUI.mono(11)).foregroundStyle(TUI.dim)
            }
            ForEach(parsed) { line in
                row(line)
                    .background(line.id % 2 == 1 ? TUI.panel.opacity(0.55) : .clear)
            }
        }
    }

    /// One entry: `▸ HH:mm:ss [tag] message` — marker+time dimmed, tag colored
    /// per source, message tinted by severity. Wrapped lines stay visually
    /// grouped by the zebra stripe and the ▸ start-of-entry marker.
    private func row(_ line: LogLine) -> some View {
        let msgColor: Color = line.isBad ? TUI.warn
            : (line.isGood ? TUI.fg : TUI.fg.opacity(0.75))
        var t = Text("▸ ").foregroundColor(TUI.dim.opacity(0.7))
        if !line.time.isEmpty {
            t = t + Text(line.time + " ").foregroundColor(TUI.dim)
        }
        if !line.tag.isEmpty {
            t = t + Text("[\(line.tag)] ").foregroundColor(line.tagColor)
        }
        t = t + Text(line.msg).foregroundColor(msgColor)
        return t
            .font(TUI.mono(11))
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, 2)
            .padding(.horizontal, 4)
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
