import AppIntents
import Foundation

/// The Now Playing widget's play/pause button (iOS 17 interactive widgets).
///
/// Compiled into BOTH the app and the widget target: the widget only needs the
/// TYPE for `Button(intent:)`; the system executes the app target's copy in
/// the app's own process (AudioPlaybackIntent, iOS 16.4+ — no foregrounding,
/// and the `audio` background mode lets AVPlayer actually play). The app-only
/// body is fenced behind `!WIDGET_EXTENSION` (defined on the widget target),
/// since PlaybackService/LibraryStore don't exist in the extension.
@available(iOS 16.4, *)
struct TogglePlaybackIntent: AudioPlaybackIntent {
    static var title: LocalizedStringResource = "Play / Pause"
    static var description = IntentDescription("Toggle YT Music playback.")
    static var isDiscoverable = false

    @MainActor
    func perform() async throws -> some IntentResult {
        #if !WIDGET_EXTENSION
        let pb = PlaybackService.shared
        if pb.current != nil {
            pb.togglePlayPause()
        } else if let s = LibraryStore.shared.sessions.first,
                  s.queue.indices.contains(min(max(0, s.index), s.queue.count - 1)) {
            // App process was launched in the background just for this intent:
            // resume the newest session's current track (single-track scope —
            // the full queue arms when the app is next opened).
            let idx = min(max(0, s.index), s.queue.count - 1)
            resumeCold(s.queue[idx], at: s.position)
        }
        #endif
        return .result()
    }

    #if !WIDGET_EXTENSION
    @MainActor
    private func resumeCold(_ r: SearchResult, at position: Double) {
        DebugLog.shared.log("intent", "cold resume: \(r.title)")
        PlaybackService.shared.beginLoading(title: r.title, uploader: r.uploader,
                                            thumbnail: r.thumbnail,
                                            duration: r.duration)
        DispatchQueue.global(qos: .userInitiated).async {
            let c = python_resolve_fresh(r.id)
            let json = c.map { String(cString: $0) } ?? "{}"
            if let c { free(c) }
            guard let track = Track.decode(json), track.ok,
                  track.streamAVURL != nil else {
                DebugLog.shared.log("intent", "cold resume resolve failed")
                return
            }
            DispatchQueue.main.async {
                PlaybackService.shared.play(track, startAt: position)
            }
        }
    }
    #endif
}
