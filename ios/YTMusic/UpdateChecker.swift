import Combine
import Foundation
import UserNotifications

/// Compares this build's baked-in commit (BuildInfo.sha, written by build.sh) against the
/// newest mobile-fork commit on GitHub. A sideloaded app can't self-update, so "update" is
/// a notice: an in-app banner/row plus one local notification per new commit, telling the
/// user to rebuild from the Mac (./reinstall.sh). Fail-silent on network/API errors.
final class UpdateChecker: ObservableObject {
    static let shared = UpdateChecker()

    @Published private(set) var updateAvailable = false

    private let api = URL(string:
        "https://api.github.com/repos/Dao-Xuan-Thinh/YT-Music-TUI/commits/mobile-fork")!
    private let notifiedKey = "update_notified_sha"
    private var lastCheck = Date.distantPast

    private init() {}

    /// Call on launch/foreground; throttled to one request per hour.
    func check() {
        guard BuildInfo.sha != "unknown",
              Date().timeIntervalSince(lastCheck) > 3600 else { return }
        lastCheck = Date()
        var req = URLRequest(url: api, timeoutInterval: 10)
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        URLSession.shared.dataTask(with: req) { [weak self] data, _, _ in
            guard let self, let data,
                  let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
                  let sha = obj["sha"] as? String, !sha.isEmpty else { return }
            DispatchQueue.main.async {
                let newer = sha != BuildInfo.sha
                self.updateAvailable = newer
                guard newer else { return }
                DebugLog.shared.log("update",
                    "newer build on GitHub: \(sha.prefix(7)) (this build: \(BuildInfo.sha.prefix(7)))")
                if UserDefaults.standard.string(forKey: self.notifiedKey) != sha {
                    self.notify(sha: sha)
                }
            }
        }.resume()
    }

    private func notify(sha: String) {
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { return }
            let content = UNMutableNotificationContent()
            content.title = "YTMusic update available"
            content.body = "A newer build is on GitHub — run ./reinstall.sh on the Mac."
            center.add(UNNotificationRequest(identifier: "update-\(sha)",
                                             content: content, trigger: nil))
            UserDefaults.standard.set(sha, forKey: self.notifiedKey)
        }
    }
}
