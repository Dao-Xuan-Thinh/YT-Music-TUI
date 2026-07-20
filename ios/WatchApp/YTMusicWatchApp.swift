import SwiftUI

/// watchOS companion: a remote for the iPhone app (no audio of its own).
/// Commands travel over WatchConnectivity to `WatchLink` on the phone.
@main
struct YTMusicWatchApp: App {
    var body: some Scene {
        WindowGroup {
            WatchRemoteView()
        }
    }
}
