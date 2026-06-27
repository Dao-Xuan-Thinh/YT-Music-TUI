import SwiftUI
import UIKit

/// Terminal-flavored palette + monospace helpers for the Hybrid-TUI look.
enum TUI {
    static let bg     = Color(red: 0.05, green: 0.06, blue: 0.06)
    static let panel  = Color(red: 0.09, green: 0.11, blue: 0.10)
    static let fg     = Color(red: 0.86, green: 0.89, blue: 0.86)
    static let accent = Color(red: 0.30, green: 0.92, blue: 0.55)   // terminal green
    static let dim    = Color(red: 0.46, green: 0.52, blue: 0.49)
    static let warn   = Color(red: 0.95, green: 0.45, blue: 0.45)

    static func mono(_ size: CGFloat = 14, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
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
