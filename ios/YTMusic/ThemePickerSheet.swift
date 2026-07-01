import SwiftUI

/// Theme chooser presented from the footer skin button (a popup, not a cycle).
struct ThemePickerSheet: View {
    @ObservedObject private var theme = ThemeManager.shared
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            TUI.bg.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("⊞ themes").font(TUI.mono(18, .bold)).foregroundStyle(TUI.accent)
                    Spacer()
                    Text("done").font(TUI.mono(14, .bold)).foregroundStyle(TUI.accent)
                        .onTapGesture { dismiss() }
                }
                ScrollView {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(theme.all) { t in
                            ThemeRow(theme: t, selected: t.name == theme.current.name) {
                                ThemeManager.shared.select(t.name)
                            }
                        }
                    }
                }
            }
            .padding(18)
        }
        .foregroundStyle(TUI.fg).font(TUI.mono()).tint(TUI.accent)
        .preferredColorScheme(theme.current.dark ? .dark : .light)
    }
}

/// One selectable theme row with a swatch preview (shared by the picker + Settings).
struct ThemeRow: View {
    let theme: AppTheme
    let selected: Bool
    let action: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Text(selected ? "◉" : "○").foregroundStyle(theme.accent)
            Text(theme.name).foregroundStyle(selected ? TUI.fg : TUI.dim)
            Spacer()
            HStack(spacing: 4) {
                ForEach(Array((theme.wave ?? [theme.accent]).prefix(5).enumerated()),
                        id: \.offset) { _, c in
                    RoundedRectangle(cornerRadius: 2).fill(c).frame(width: 14, height: 14)
                }
            }
        }
        .font(TUI.mono(14)).frame(height: 30).contentShape(Rectangle())
        .onTapGesture(perform: action)
    }
}
