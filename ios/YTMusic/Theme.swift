import SwiftUI
import UIKit

/// One color theme. `wave` is the (optional) color-wave palette used to animate the
/// now-playing text while a track is playing (nil = no wave for this theme).
struct AppTheme: Identifiable, Equatable {
    let name: String
    let bg: Color
    let panel: Color
    let fg: Color
    let accent: Color
    let dim: Color
    let warn: Color
    let wave: [Color]?
    let dark: Bool
    var id: String { name }
}

/// Holds the active theme + the picker list, and persists the choice. Views that read
/// `TUI.*` re-render on change because the root views observe this object. Not `@MainActor`
/// (so the nonisolated `TUI` accessors can read `current`); only ever touched on the UI thread.
final class ThemeManager: ObservableObject {
    static let shared = ThemeManager()
    private let key = "theme_name"

    @Published var current: AppTheme

    let all: [AppTheme] = AppTheme.builtins

    private init() {
        let saved = UserDefaults.standard.string(forKey: key)
        current = AppTheme.builtins.first { $0.name == saved } ?? AppTheme.builtins[0]
    }

    func select(_ name: String) {
        guard let t = all.first(where: { $0.name == name }) else { return }
        current = t
        UserDefaults.standard.set(name, forKey: key)
    }

    func cycle() {
        guard let i = all.firstIndex(of: current) else { return }
        select(all[(i + 1) % all.count].name)
    }
}

/// Terminal-flavored palette + monospace helpers. The colors are now dynamic — they read
/// the active `ThemeManager.shared.current`, so existing `TUI.accent`-style call sites keep
/// working and follow the selected theme.
enum TUI {
    static var theme: AppTheme { ThemeManager.shared.current }
    static var bg: Color     { theme.bg }
    static var panel: Color  { theme.panel }
    static var fg: Color     { theme.fg }
    static var accent: Color { theme.accent }
    static var dim: Color    { theme.dim }
    static var warn: Color   { theme.warn }

    static func mono(_ size: CGFloat = 14, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}

extension AppTheme {
    /// Build a theme from desktop-style hex (mirrors `main.py` CUSTOM_THEMES): primary→accent,
    /// background→bg, foreground→fg, error→warn; `dim` derived as a fg/bg blend.
    static func make(_ name: String, dark: Bool, bg: String, panel: String, fg: String,
                     accent: String, warn: String, wave: [String]?) -> AppTheme {
        let bgC = Color(hex: bg), fgC = Color(hex: fg)
        return AppTheme(name: name, bg: bgC, panel: Color(hex: panel), fg: fgC,
                        accent: Color(hex: accent), dim: .lerp(fgC, bgC, 0.5),
                        warn: Color(hex: warn), wave: wave?.map { Color(hex: $0) }, dark: dark)
    }

    // The default green terminal look + the desktop's 14 hand-picked themes & wave palettes.
    static let builtins: [AppTheme] = [
        make("terminal", dark: true, bg: "#0d0f0f", panel: "#171c19", fg: "#dbe3db",
             accent: "#4deb8c", warn: "#f27373", wave: ["#4deb8c", "#33cccc", "#99f273"]),
        make("synthwave", dark: true, bg: "#16111f", panel: "#2f2342", fg: "#f7f0ff",
             accent: "#ff5fd2", warn: "#fe4450", wave: ["#ff5fd2", "#b967ff", "#36f9f6", "#b967ff"]),
        make("vaporwave", dark: true, bg: "#1a1426", panel: "#352a4d", fg: "#fdf6ff",
             accent: "#ff71ce", warn: "#ff6e6e", wave: ["#ff71ce", "#b967ff", "#01cdfe", "#05ffa1"]),
        make("matrix", dark: true, bg: "#020a02", panel: "#0a2010", fg: "#c8ffc8",
             accent: "#39ff14", warn: "#ff3b3b", wave: ["#0a3d0a", "#39ff14", "#aaff66", "#39ff14"]),
        make("prism", dark: true, bg: "#0f0f14", panel: "#24242f", fg: "#fafafa",
             accent: "#ff4d4d", warn: "#ff4d6d",
             wave: ["#ff4d4d", "#ffa64d", "#ffe24d", "#4dff88", "#4dd2ff", "#7d4dff", "#ff4dd2"]),
        make("ember", dark: true, bg: "#170d08", panel: "#331c0d", fg: "#fff1e0",
             accent: "#ff7b29", warn: "#ff4d34", wave: ["#ff3b1f", "#ff7b29", "#ffb454", "#ffd45e"]),
        make("deep-ocean", dark: true, bg: "#04121a", panel: "#0c3142", fg: "#e0f7ff",
             accent: "#2bd6c6", warn: "#ff5d73", wave: ["#0a3142", "#2bd6c6", "#5ef0ff", "#3a8fff"]),
        make("blood-moon", dark: true, bg: "#120406", panel: "#330f15", fg: "#ffe6e6",
             accent: "#ff3b54", warn: "#ff2e4d", wave: ["#5a0010", "#ff3b54", "#ff7a45", "#ff3b54"]),
        make("aurora", dark: true, bg: "#06121a", panel: "#123042", fg: "#ecfdf5",
             accent: "#5eead4", warn: "#fb7185", wave: ["#34d399", "#5eead4", "#818cf8", "#c084fc"]),
        make("sakura", dark: false, bg: "#fff0f5", panel: "#ffd0e0", fg: "#3a2230",
             accent: "#e35d8f", warn: "#e0445d", wave: nil),
        make("arctic", dark: false, bg: "#f0f6ff", panel: "#cfe0f5", fg: "#0d2438",
             accent: "#2f6fed", warn: "#e0445d", wave: nil),
        make("solar-flare", dark: true, bg: "#1a1205", panel: "#3a2a0c", fg: "#fff8e1",
             accent: "#ffb300", warn: "#e53935", wave: ["#ff7043", "#ffb300", "#ffd54f", "#fff3c0"]),
        make("cyberpunk", dark: true, bg: "#0a0e12", panel: "#1a2630", fg: "#f5fdff",
             accent: "#fcee0a", warn: "#ff2a6d", wave: ["#ff2a6d", "#fcee0a", "#00f0ff", "#ff2a6d"]),
        make("mono-amber", dark: true, bg: "#0c0a06", panel: "#1f1a0c", fg: "#ffcf7a",
             accent: "#ffb000", warn: "#ff5e5e", wave: nil),
        make("nebula", dark: true, bg: "#0c0818", panel: "#22183b", fg: "#f3eaff",
             accent: "#a06bff", warn: "#ff5d8f", wave: ["#6b8bff", "#a06bff", "#ff6bd6", "#a06bff"]),
    ]
}

extension Color {
    /// Init from a "#rrggbb" hex string.
    init(hex: String) {
        let h = hex.hasPrefix("#") ? String(hex.dropFirst()) : hex
        var v: UInt64 = 0
        Scanner(string: h).scanHexInt64(&v)
        self.init(red: Double((v >> 16) & 0xff) / 255,
                  green: Double((v >> 8) & 0xff) / 255,
                  blue: Double(v & 0xff) / 255)
    }
}

extension Color {
    /// Linear RGB interpolation between two colors (for the color-wave).
    static func lerp(_ a: Color, _ b: Color, _ t: Double) -> Color {
        let ua = UIColor(a), ub = UIColor(b)
        var ar: CGFloat = 0, ag: CGFloat = 0, ab: CGFloat = 0, aa: CGFloat = 0
        var br: CGFloat = 0, bg: CGFloat = 0, bb: CGFloat = 0, ba: CGFloat = 0
        ua.getRed(&ar, green: &ag, blue: &ab, alpha: &aa)
        ub.getRed(&br, green: &bg, blue: &bb, alpha: &ba)
        let f = CGFloat(max(0, min(1, t)))
        return Color(red: Double(ar + (br - ar) * f),
                     green: Double(ag + (bg - ag) * f),
                     blue: Double(ab + (bb - ab) * f))
    }
}

/// Text whose characters flow through a color-wave while `active`. Falls back to a static
/// color otherwise. Uses a ~12 fps timeline so it costs nothing when not shown (the view is
/// only mounted where a wave is wanted).
struct WaveText: View {
    let text: String
    let palette: [Color]?
    var font: Font = TUI.mono(18, .bold)
    var fallback: Color = TUI.accent
    var active: Bool
    var lineLimit: Int = 2

    var body: some View {
        Group {
            if active, let pal = palette, pal.count >= 2 {
                TimelineView(.periodic(from: .now, by: 0.08)) { tl in
                    let t = tl.date.timeIntervalSinceReferenceDate * 0.3
                    let phase = CGFloat(t - t.rounded(.down))   // 0..<1, loops
                    Text(text).foregroundStyle(waveGradient(pal, phase))
                }
            } else {
                Text(text).foregroundStyle(fallback)
            }
        }
        .font(font)
        .lineLimit(lineLimit)
        .truncationMode(.tail)
    }

    /// A horizontally-scrolling gradient that fills the text glyphs — a flowing wave that
    /// (unlike per-character coloring) never changes the text's layout, so long titles
    /// truncate instead of overlapping.
    private func waveGradient(_ pal: [Color], _ phase: CGFloat) -> LinearGradient {
        let colors = pal + pal + pal + [pal[0]]   // repeated for a seamless scroll
        let span: CGFloat = 3
        let shift = phase * span
        return LinearGradient(
            gradient: Gradient(colors: colors),
            startPoint: UnitPoint(x: -span + shift, y: 0.5),
            endPoint: UnitPoint(x: shift, y: 0.5))
    }
}

extension UIImage {
    /// Center-crop to a 1:1 square (lock-screen artwork expects square).
    func squareCropped() -> UIImage {
        let side = min(size.width, size.height)
        let origin = CGPoint(x: (size.width - side) / 2, y: (size.height - side) / 2)
        let rect = CGRect(origin: CGPoint(x: -origin.x, y: -origin.y), size: size)
        let fmt = UIGraphicsImageRendererFormat.default()
        fmt.scale = scale
        return UIGraphicsImageRenderer(size: CGSize(width: side, height: side), format: fmt)
            .image { _ in draw(in: rect) }
    }
}

/// A full-width ─────── rule (overflow is clipped).
struct TUIDivider: View {
    var body: some View {
        Text(String(repeating: "─", count: 200))
            .font(TUI.mono(12))
            .foregroundStyle(TUI.dim)
            .lineLimit(1)
            .frame(maxWidth: .infinity, alignment: .leading)
            .clipped()
    }
}
