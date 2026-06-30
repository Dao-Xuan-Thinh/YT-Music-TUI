import Combine
import Foundation

/// Lightweight user settings persisted to `UserDefaults` (theme lives in `ThemeManager`).
/// Mirrors the desktop `config.py` notions of a default search source + volume.
final class AppConfig: ObservableObject {
    static let shared = AppConfig()
    private let d = UserDefaults.standard

    @Published var defaultSource: SearchSource {
        didSet { d.set(defaultSource.rawValue, forKey: "default_source") }
    }
    @Published var defaultVolume: Double {
        didSet { d.set(defaultVolume, forKey: "default_volume") }
    }

    private init() {
        defaultSource = SearchSource(rawValue: d.string(forKey: "default_source") ?? "") ?? .ytm
        defaultVolume = (d.object(forKey: "default_volume") as? Double) ?? 1.0
    }
}
