import Combine
import Foundation
import UIKit

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

    // Listen-stats sync (mirrors the desktop's stats_* config keys). The token
    // lives in the Keychain — never in UserDefaults and never in the App Group
    // the widget reads, so the widget has no access to it (and no network).
    @Published var statsToken: String {
        didSet { Keychain.set("stats_token", statsToken) }
    }
    @Published var statsDeviceName: String {
        didSet { d.set(statsDeviceName, forKey: "stats_device_name") }
    }
    var statsGistID: String {
        get { d.string(forKey: "stats_gist_id") ?? "" }
        set { d.set(newValue, forKey: "stats_gist_id") }
    }
    private(set) var statsDeviceID: String

    private init() {
        defaultSource = SearchSource(rawValue: d.string(forKey: "default_source") ?? "") ?? .ytm
        defaultVolume = (d.object(forKey: "default_volume") as? Double) ?? 1.0
        // Token: Keychain, with a one-time migration from the old UserDefaults slot.
        if let legacy = d.string(forKey: "stats_token"), !legacy.isEmpty,
           Keychain.get("stats_token") == nil {
            Keychain.set("stats_token", legacy)
        }
        d.removeObject(forKey: "stats_token")
        statsToken = Keychain.get("stats_token") ?? ""
        statsDeviceName = d.string(forKey: "stats_device_name") ?? UIDevice.current.name
        if let id = d.string(forKey: "stats_device_id"), !id.isEmpty {
            statsDeviceID = id
        } else {
            let id = UUID().uuidString.lowercased()
            d.set(id, forKey: "stats_device_id")
            statsDeviceID = id
        }
    }
}
