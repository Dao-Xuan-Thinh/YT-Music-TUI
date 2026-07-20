import SwiftUI

@main
struct YTMusicApp: App {
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .onChange(of: scenePhase) { phase in
            if phase == .background { BackgroundRefresher.schedule() }
        }
        // Registers AND handles the refresh task (SwiftUI wires BGTaskScheduler
        // early enough for background launches); Swift-concurrency cancellation
        // doubles as the expiration handler.
        .backgroundTask(.appRefresh(BackgroundRefresher.taskID)) {
            await BackgroundRefresher.run()
        }
    }
}
