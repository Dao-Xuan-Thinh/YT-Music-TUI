import BackgroundTasks
import Foundation

/// Periodic background upkeep (BGAppRefreshTask, ~every 6h when iOS allows it):
///   1. Google-session keep-alive: GET music.youtube.com with the stored cookie
///      header, harvest rotated Set-Cookie values, merge + re-persist. This is
///      the background analog of AccountStore.silentWebRefresh — but WKWebView
///      cannot be trusted from a background launch, so it's a plain URLSession
///      round-trip against the Keychain-stored header instead. The WK web-store
///      jar is left alone (foreground refresh keeps that one alive).
///   2. Stats gist sync (StatsStore, awaited so the PATCH isn't cut off).
///   3. Update check (cheap fire-and-forget).
/// Scheduling is chained: the handler re-submits before doing any work, and the
/// app also submits whenever it backgrounds. Everything is fail-silent — iOS
/// grants these launches opportunistically and may not run us for days.
enum BackgroundRefresher {
    static let taskID = "com.ytmtui.YTMusic.refresh"

    static func schedule() {
        let req = BGAppRefreshTaskRequest(identifier: taskID)
        req.earliestBeginDate = Date(timeIntervalSinceNow: 6 * 3600)
        try? BGTaskScheduler.shared.submit(req)   // resubmits replace silently
    }

    static func run() async {
        schedule()   // chain the next run first — a crash below must not break it
        DebugLog.shared.log("bg", "background refresh started")
        await refreshCookies()
        await withCheckedContinuation { (cont: CheckedContinuation<Void, Never>) in
            Task { @MainActor in
                StatsStore.shared.sync(force: true) { cont.resume() }
            }
        }
        UpdateChecker.shared.check()
        DebugLog.shared.log("bg", "background refresh finished")
    }

    // MARK: - Cookie keep-alive

    private static func refreshCookies() async {
        guard let header = Keychain.get(AccountStore.cookieKeychainKey),
              header.contains("SAPISID") else {
            DebugLog.shared.log("bg", "no stored session — cookie refresh skipped")
            return
        }
        var req = URLRequest(url: URL(string: "https://music.youtube.com/")!)
        req.setValue(header, forHTTPHeaderField: "Cookie")
        req.setValue(AccountStore.desktopUA, forHTTPHeaderField: "User-Agent")
        let cfg = URLSessionConfiguration.ephemeral
        cfg.httpShouldSetCookies = false     // manual jar — nothing leaks elsewhere
        cfg.httpCookieStorage = nil
        cfg.timeoutIntervalForResource = 20
        guard let (_, resp) = try? await URLSession(configuration: cfg).data(for: req),
              let http = resp as? HTTPURLResponse else {
            DebugLog.shared.log("bg", "cookie keep-alive: request failed")
            return
        }
        let rotated = HTTPCookie.cookies(
            withResponseHeaderFields: (http.allHeaderFields as? [String: String]) ?? [:],
            for: http.url ?? URL(string: "https://music.youtube.com/")!)
        guard !rotated.isEmpty else {
            DebugLog.shared.log("bg", "cookie keep-alive: nothing rotated (HTTP \(http.statusCode))")
            return
        }
        // Merge rotated values into the stored header, preserving cookie order.
        var jar: [String: String] = [:]
        var order: [String] = []
        for pair in header.components(separatedBy: "; ") {
            guard let eq = pair.firstIndex(of: "=") else { continue }
            let k = String(pair[..<eq])
            if jar[k] == nil { order.append(k) }
            jar[k] = String(pair[pair.index(after: eq)...])
        }
        for c in rotated where !c.value.isEmpty {
            if jar[c.name] == nil { order.append(c.name) }
            jar[c.name] = c.value
        }
        let merged = order.compactMap { k in jar[k].map { "\(k)=\($0)" } }
            .joined(separator: "; ")
        Keychain.set(AccountStore.cookieKeychainKey, merged)
        DebugLog.shared.log("bg", "cookie keep-alive: rotated \(rotated.count) cookie(s)")
        // Refresh the live Python session only if the interpreter already runs
        // (app suspended in background). Never cold-start CPython in a BG task.
        if python_ready() != 0 {
            DispatchQueue.global(qos: .utility).async {
                if let c = python_set_auth(merged) { free(c) }
            }
        }
    }
}
