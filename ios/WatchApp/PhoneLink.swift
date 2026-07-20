import Combine
import Foundation
import WatchConnectivity

/// Watch → phone link. `sendMessage` needs the iPhone app reachable (it's the
/// live-session channel), so every command is best-effort and the UI says so
/// when the phone isn't answering.
final class PhoneLink: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = PhoneLink()

    @Published private(set) var title = ""
    @Published private(set) var artist = ""
    @Published private(set) var isPlaying = false
    @Published private(set) var reachable = false

    private override init() {
        super.init()
    }

    func start() {
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    /// Ask the phone for its now-playing state.
    func refresh() { send("status") }

    func send(_ cmd: String) {
        let session = WCSession.default
        guard session.activationState == .activated, session.isReachable else {
            DispatchQueue.main.async { self.reachable = false }
            return
        }
        session.sendMessage(["cmd": cmd], replyHandler: { reply in
            DispatchQueue.main.async { self.apply(reply) }
        }, errorHandler: { _ in
            DispatchQueue.main.async { self.reachable = false }
        })
    }

    private func apply(_ reply: [String: Any]) {
        reachable = true
        title = reply["title"] as? String ?? ""
        artist = reply["artist"] as? String ?? ""
        isPlaying = reply["isPlaying"] as? Bool ?? false
    }

    // MARK: - WCSessionDelegate

    func session(_ session: WCSession, activationDidCompleteWith state: WCSessionActivationState,
                 error: Error?) {
        DispatchQueue.main.async {
            self.reachable = session.isReachable
            if state == .activated { self.refresh() }
        }
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        DispatchQueue.main.async {
            self.reachable = session.isReachable
            if session.isReachable { self.refresh() }
        }
    }
}
