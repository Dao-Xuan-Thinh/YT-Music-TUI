import Combine
import Foundation
import WebKit

/// Holds the signed-in YouTube account session. The cookie string (from the in-app web view
/// or a paste) is verified + applied to the embedded Python (`python_set_auth` →
/// resolve.set_auth → ytmusicapi browser auth) and persisted to Application Support so the
/// session is re-armed at launch. Sensitive: stored outside Documents (not file-shared).
///
/// Staleness: Google rotates the session cookies (__Secure-*PSIDTS) regularly, so a frozen
/// snapshot eventually expires — the desktop app survives because it re-reads the live
/// browser jar every launch. The mobile analog is `silentWebRefresh()`: at every launch we
/// reload music.youtube.com in a hidden web view (the persistent WKWebsiteDataStore still
/// holds the Google session from the in-app sign-in), let Google rotate the cookies, then
/// re-capture + persist them. As long as the app is opened now and then, the session
/// never goes stale. If it's truly dead, the UI says so instead of silently breaking.
final class AccountStore: ObservableObject {
    static let shared = AccountStore()

    @Published private(set) var name: String = ""
    @Published private(set) var signedIn = false
    @Published private(set) var working = false
    @Published var lastError: String?

    private let cookieURL: URL
    private var refreshWebView: WKWebView?   // retained while the silent refresh runs

    private init() {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        cookieURL = dir.appendingPathComponent("yt_account_cookie.txt")
    }

    private var storedCookie: String? {
        let s = try? String(contentsOf: cookieURL, encoding: .utf8)
        return (s?.isEmpty == false) ? s : nil
    }

    /// Re-arm the Python session from the stored cookie at launch, then silently refresh
    /// the cookies from the in-app web session (no-op if signed out). Main thread only.
    func restore() {
        guard let cookie = storedCookie else { return }
        apply(cookie, persist: false)
        silentWebRefresh()
    }

    /// Verify + sign in with a cookie string (web-view capture or paste).
    func signIn(cookie: String) { apply(cookie, persist: true) }

    func signOut() {
        try? FileManager.default.removeItem(at: cookieURL)
        name = ""
        signedIn = false
        lastError = nil
        // Clear the web-view session too, or the next launch's silent refresh would
        // re-capture it and sign this account straight back in.
        WKWebsiteDataStore.default().removeData(
            ofTypes: [WKWebsiteDataTypeCookies], modifiedSince: .distantPast) {}
        DebugLog.shared.log("auth", "signed out")
        DispatchQueue.global(qos: .utility).async {
            if let c = python_set_auth("") { free(c) }   // clear the Python session too
        }
    }

    // MARK: - Silent session refresh

    /// Reload music.youtube.com in a hidden web view so Google rotates the session
    /// cookies, then re-capture + persist them (the auto re-sign-in).
    private func silentWebRefresh() {
        guard refreshWebView == nil else { return }
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .default()
        let wv = WKWebView(frame: .zero, configuration: cfg)
        wv.customUserAgent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
        refreshWebView = wv
        DebugLog.shared.log("auth", "silent session refresh: loading music.youtube.com")
        wv.load(URLRequest(url: URL(string: "https://music.youtube.com/")!))
        // Give the page a few seconds to land (and Set-Cookie to rotate), then capture —
        // whatever cookies exist by then are still the freshest available.
        DispatchQueue.main.asyncAfter(deadline: .now() + 8) { [weak self] in
            self?.captureFromWebStore()
        }
    }

    private func captureFromWebStore() {
        WKWebsiteDataStore.default().httpCookieStore.getAllCookies { [weak self] cookies in
            guard let self else { return }
            self.refreshWebView = nil
            let rel = cookies.filter {
                $0.domain.contains("google") || $0.domain.contains("youtube")
            }
            let str = rel.map { "\($0.name)=\($0.value)" }.joined(separator: "; ")
            guard str.contains("SAPISID") else {
                // Paste-based sign-in (no web session) or the web session is gone.
                DebugLog.shared.log("auth", "web store holds no session — silent refresh skipped")
                return
            }
            DebugLog.shared.log("auth", "captured rotated session cookies — re-verifying")
            self.apply(str, persist: true)
        }
    }

    // MARK: - Apply

    private func apply(_ cookie: String, persist: Bool) {
        working = true
        DispatchQueue.global(qos: .userInitiated).async {
            let c = python_set_auth(cookie)
            let json = c.map { String(cString: $0) } ?? "{}"
            if let c { free(c) }
            let obj = (try? JSONSerialization.jsonObject(with: Data(json.utf8))) as? [String: Any]
            let ok = (obj?["ok"] as? Bool) ?? false
            let nm = (obj?["name"] as? String) ?? ""
            let reason = (obj?["reason"] as? String) ?? ""
            DispatchQueue.main.async {
                self.working = false
                if ok {
                    self.name = nm
                    self.signedIn = true
                    self.lastError = nil
                    DebugLog.shared.log("auth", "signed in as \(nm)")
                    if persist {
                        try? cookie.write(to: self.cookieURL, atomically: true, encoding: .utf8)
                    }
                } else {
                    self.signedIn = false
                    self.name = ""
                    DebugLog.shared.log("auth", "sign-in failed (\(reason.isEmpty ? "unknown" : reason))")
                    self.lastError = reason == "expired"
                        ? "Session expired — sign in with the browser again."
                        : "Couldn't verify that session — not logged in, or the cookies are missing/expired."
                }
            }
        }
    }
}
