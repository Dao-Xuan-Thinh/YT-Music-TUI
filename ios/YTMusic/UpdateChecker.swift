import Combine
import Foundation
import UserNotifications

/// Compares this build's baked-in commit (BuildInfo.sha, written by build.sh) against the
/// newest mobile-fork commit on GitHub. A sideloaded app can't self-update, so "update" is
/// a notice: an in-app banner/row plus one local notification per new commit, telling the
/// user to rebuild from the Mac (./reinstall.sh). Fail-silent on network/API errors.
///
/// Also announces a freshly-installed build on its first launch (one notification per new
/// sha) — doubles as an end-to-end test that notifications work after every reinstall.
/// NSObject + delegate: without a UNUserNotificationCenterDelegate granting `.banner`,
/// iOS silently drops notifications while the app is foregrounded — which is exactly when
/// the install announcement fires.
final class UpdateChecker: NSObject, ObservableObject, UNUserNotificationCenterDelegate {
    static let shared = UpdateChecker()

    @Published private(set) var updateAvailable = false

    private let api = URL(string:
        "https://api.github.com/repos/Dao-Xuan-Thinh/YT-Music-TUI/commits/mobile-fork")!
    private let notifiedKey = "update_notified_sha"
    private let lastRunKey = "last_run_sha"
    private var lastCheck = Date.distantPast

    private override init() {
        super.init()
        UNUserNotificationCenter.current().delegate = self
    }

    // Show notifications as banners even while the app is in the foreground.
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification)
        async -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }

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
                    self.notify(title: "YTMusic update available",
                                body: "A newer build is on GitHub — run ./reinstall.sh on the Mac.",
                                id: "update-\(sha)")
                    UserDefaults.standard.set(sha, forKey: self.notifiedKey)
                }
            }
        }.resume()
    }

    /// First launch of a freshly-installed build → one "updated" notification.
    func announceBuildIfNew() {
        guard BuildInfo.sha != "unknown",
              UserDefaults.standard.string(forKey: lastRunKey) != BuildInfo.sha else { return }
        UserDefaults.standard.set(BuildInfo.sha, forKey: lastRunKey)
        let v = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "dev"
        DebugLog.shared.log("update", "new build installed: v\(v) @ \(BuildInfo.sha.prefix(7))")
        notify(title: "YTMusic updated",
               body: "Now running v\(v) — build \(BuildInfo.sha.prefix(7)).",
               id: "installed-\(BuildInfo.sha)")
    }

    private func notify(title: String, body: String, id: String) {
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { return }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            center.add(UNNotificationRequest(identifier: id, content: content, trigger: nil))
        }
    }
}
