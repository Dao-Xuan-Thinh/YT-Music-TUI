import Combine
import Foundation

/// Holds the signed-in YouTube account session. The cookie string (from the in-app web view
/// or a paste) is verified + applied to the embedded Python (`python_set_auth` →
/// resolve.set_auth → ytmusicapi browser auth) and persisted to Application Support so the
/// session is re-armed at launch. Sensitive: stored outside Documents (not file-shared).
final class AccountStore: ObservableObject {
    static let shared = AccountStore()

    @Published private(set) var name: String = ""
    @Published private(set) var signedIn = false
    @Published private(set) var working = false
    @Published var lastError: String?

    private let cookieURL: URL

    private init() {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        cookieURL = dir.appendingPathComponent("yt_account_cookie.txt")
    }

    private var storedCookie: String? {
        let s = try? String(contentsOf: cookieURL, encoding: .utf8)
        return (s?.isEmpty == false) ? s : nil
    }

    /// Re-arm the Python session from the stored cookie at launch (no-op if signed out).
    func restore() {
        guard let cookie = storedCookie else { return }
        apply(cookie, persist: false)
    }

    /// Verify + sign in with a cookie string (web-view capture or paste).
    func signIn(cookie: String) { apply(cookie, persist: true) }

    func signOut() {
        try? FileManager.default.removeItem(at: cookieURL)
        name = ""
        signedIn = false
        lastError = nil
        DispatchQueue.global(qos: .utility).async {
            if let c = python_set_auth("") { free(c) }   // clear the Python session too
        }
    }

    private func apply(_ cookie: String, persist: Bool) {
        working = true
        lastError = nil
        DispatchQueue.global(qos: .userInitiated).async {
            let c = python_set_auth(cookie)
            let json = c.map { String(cString: $0) } ?? "{}"
            if let c { free(c) }
            let obj = (try? JSONSerialization.jsonObject(with: Data(json.utf8))) as? [String: Any]
            let ok = (obj?["ok"] as? Bool) ?? false
            let nm = (obj?["name"] as? String) ?? ""
            DispatchQueue.main.async {
                self.working = false
                if ok {
                    self.name = nm
                    self.signedIn = true
                    if persist {
                        try? cookie.write(to: self.cookieURL, atomically: true, encoding: .utf8)
                    }
                } else {
                    self.signedIn = false
                    self.name = ""
                    if persist {
                        self.lastError = "Couldn't verify that session — not logged in, or the cookies are missing/expired."
                    }
                }
            }
        }
    }
}
