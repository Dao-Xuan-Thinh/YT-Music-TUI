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
    static let builtins: [AppTheme] = [terminal, amber, synthwave, ice, matrix, mono]

    static let terminal = AppTheme(
        name: "terminal",
        bg: Color(red: 0.05, green: 0.06, blue: 0.06),
        panel: Color(red: 0.09, green: 0.11, blue: 0.10),
        fg: Color(red: 0.86, green: 0.89, blue: 0.86),
        accent: Color(red: 0.30, green: 0.92, blue: 0.55),
        dim: Color(red: 0.46, green: 0.52, blue: 0.49),
        warn: Color(red: 0.95, green: 0.45, blue: 0.45),
        wave: [Color(red: 0.30, green: 0.92, blue: 0.55),
               Color(red: 0.20, green: 0.80, blue: 0.80),
               Color(red: 0.60, green: 0.95, blue: 0.45)])

    static let amber = AppTheme(
        name: "amber",
        bg: Color(red: 0.06, green: 0.05, blue: 0.03),
        panel: Color(red: 0.12, green: 0.09, blue: 0.04),
        fg: Color(red: 0.93, green: 0.84, blue: 0.66),
        accent: Color(red: 1.00, green: 0.74, blue: 0.20),
        dim: Color(red: 0.55, green: 0.45, blue: 0.28),
        warn: Color(red: 0.96, green: 0.45, blue: 0.35),
        wave: [Color(red: 1.00, green: 0.74, blue: 0.20),
               Color(red: 0.98, green: 0.52, blue: 0.12),
               Color(red: 1.00, green: 0.88, blue: 0.40)])

    static let synthwave = AppTheme(
        name: "synthwave",
        bg: Color(red: 0.07, green: 0.04, blue: 0.11),
        panel: Color(red: 0.13, green: 0.08, blue: 0.20),
        fg: Color(red: 0.90, green: 0.85, blue: 0.98),
        accent: Color(red: 1.00, green: 0.32, blue: 0.71),
        dim: Color(red: 0.50, green: 0.42, blue: 0.62),
        warn: Color(red: 1.00, green: 0.50, blue: 0.45),
        wave: [Color(red: 1.00, green: 0.32, blue: 0.71),
               Color(red: 0.45, green: 0.55, blue: 1.00),
               Color(red: 0.30, green: 0.90, blue: 0.95),
               Color(red: 0.78, green: 0.40, blue: 1.00)])

    static let ice = AppTheme(
        name: "ice",
        bg: Color(red: 0.04, green: 0.06, blue: 0.09),
        panel: Color(red: 0.08, green: 0.12, blue: 0.17),
        fg: Color(red: 0.84, green: 0.92, blue: 0.98),
        accent: Color(red: 0.40, green: 0.80, blue: 1.00),
        dim: Color(red: 0.42, green: 0.52, blue: 0.62),
        warn: Color(red: 0.95, green: 0.55, blue: 0.55),
        wave: [Color(red: 0.40, green: 0.80, blue: 1.00),
               Color(red: 0.30, green: 0.55, blue: 0.95),
               Color(red: 0.70, green: 0.92, blue: 1.00)])

    static let matrix = AppTheme(
        name: "matrix",
        bg: Color(red: 0.02, green: 0.04, blue: 0.02),
        panel: Color(red: 0.04, green: 0.09, blue: 0.04),
        fg: Color(red: 0.62, green: 0.85, blue: 0.62),
        accent: Color(red: 0.20, green: 1.00, blue: 0.30),
        dim: Color(red: 0.32, green: 0.50, blue: 0.32),
        warn: Color(red: 0.90, green: 0.55, blue: 0.30),
        wave: [Color(red: 0.20, green: 1.00, blue: 0.30),
               Color(red: 0.10, green: 0.70, blue: 0.20),
               Color(red: 0.55, green: 1.00, blue: 0.45)])

    static let mono = AppTheme(
        name: "mono",
        bg: Color(red: 0.06, green: 0.06, blue: 0.06),
        panel: Color(red: 0.12, green: 0.12, blue: 0.12),
        fg: Color(red: 0.82, green: 0.82, blue: 0.82),
        accent: Color(red: 0.90, green: 0.90, blue: 0.90),
        dim: Color(red: 0.48, green: 0.48, blue: 0.48),
        warn: Color(red: 0.90, green: 0.55, blue: 0.55),
        wave: nil)
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
        if active, let pal = palette, pal.count >= 2 {
            TimelineView(.periodic(from: .now, by: 0.08)) { tl in
                let phase = tl.date.timeIntervalSinceReferenceDate * 3.0
                HStack(spacing: 0) {
                    ForEach(Array(text.enumerated()), id: \.offset) { i, ch in
                        Text(String(ch)).foregroundStyle(color(pal, Double(i), phase))
                    }
                }
                .font(font)
                .lineLimit(1)
            }
        } else {
            Text(text).font(font).foregroundStyle(fallback).lineLimit(lineLimit)
        }
    }

    private func color(_ pal: [Color], _ index: Double, _ phase: Double) -> Color {
        let n = Double(pal.count)
        var pos = (index * 0.5 + phase).truncatingRemainder(dividingBy: n)
        if pos < 0 { pos += n }
        let i0 = Int(pos) % pal.count
        let i1 = (i0 + 1) % pal.count
        return .lerp(pal[i0], pal[i1], pos - Double(Int(pos)))
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
