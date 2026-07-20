import Foundation
import WatchConnectivity

/// Phone side of the watch remote. The watch sends {cmd: status|playpause|
/// next|prev} and gets back the now-playing state; commands run through the
/// same paths as the lock-screen remote controls.
///
/// Compile- and run-clean with no watch paired: `WCSession.isSupported()` is
/// false on iPad and activation simply never reports a reachable counterpart.
final class WatchLink: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = WatchLink()

    weak var vm: PlayerViewModel?

    private override init() {
        super.init()
    }

    func start() {
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    // MARK: - WCSessionDelegate

    func session(_ session: WCSession, activationDidCompleteWith state: WCSessionActivationState,
                 error: Error?) {
        if let error {
            DebugLog.shared.log("watch", "activation failed: \(error.localizedDescription)")
        } else {
            DebugLog.shared.log("watch", "session activated (state \(state.rawValue))")
        }
    }

    func sessionDidBecomeInactive(_ session: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        session.activate()   // re-activate for the next paired watch
    }

    func session(_ session: WCSession, didReceiveMessage message: [String: Any],
                 replyHandler: @escaping ([String: Any]) -> Void) {
        DispatchQueue.main.async {
            let pb = PlaybackService.shared
            switch message["cmd"] as? String {
            case "playpause":
                if pb.current != nil {
                    pb.togglePlayPause()
                } else {
                    self.vm?.resumePending()   // nothing loaded → resume the armed session
                }
            case "next":
                pb.onNext?()
            case "prev":
                pb.onPrevious?()
            default:
                break   // "status" — just report below
            }
            replyHandler(["title": pb.current?.title ?? "",
                          "artist": pb.current?.uploader ?? "",
                          "isPlaying": pb.isPlaying])
        }
    }
}
