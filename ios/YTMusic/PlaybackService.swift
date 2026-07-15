import AVFoundation
import Combine
import Foundation
import MediaPlayer
import QuartzCore
import UIKit

/// Owns all audio playback: AVPlayer + AVAudioSession (background mode) +
/// MPNowPlayingInfoCenter / MPRemoteCommandCenter (lock-screen / Control-Center / AirPods).
final class PlaybackService: ObservableObject {
    static let shared = PlaybackService()

    @Published private(set) var current: Track?
    @Published private(set) var isPlaying = false
    @Published private(set) var position: Double = 0   // seconds
    @Published private(set) var duration: Double = 0   // seconds
    @Published private(set) var ready = false          // item ready to play

    /// Fired when the current item plays to its end (used by the VM to auto-advance).
    var onEnded: (() -> Void)?
    /// Lock-screen / remote next & previous (wired to the VM's queue navigation).
    var onNext: (() -> Void)?
    var onPrevious: (() -> Void)?

    @Published var volume: Double = 1.0 {
        didSet { player.volume = Float(max(0, min(1, volume))) }
    }

    private let player = AVPlayer()
    private var timeObserver: Any?
    private var statusObs: NSKeyValueObservation?
    private var rateObs: NSKeyValueObservation?
    private var artwork: MPMediaItemArtwork?
    private var endedFired = false   // de-dupe end detection (metadata vs AVPlayer)
    private var pendingSeek: Double?  // resume offset, applied once the item is ready
    private var statsLastPos: Double? // previous observer position (listen-time deltas)

    // Real-time audio spectrum for the now-playing equalizer (MTAudioProcessingTap → FFT).
    let levelProcessor = AudioLevelProcessor(bands: 16)
    /// Latest band levels (0…1). Empty/ stale when the tap isn't feeding (→ UI falls back).
    var audioLevels: [Float] {
        let s = levelProcessor.snapshot()
        return (CACurrentMediaTime() - s.time < 0.4) ? s.levels : []
    }

    private init() {
        configureAudioSession()
        configureRemoteCommands()
        observePlayer()
        volume = AppConfig.shared.defaultVolume
    }

    // MARK: - Public transport

    func play(_ track: Track, startAt: Double = 0) {
        guard let url = track.streamAVURL else {
            NSLog("[playback] track has no stream URL"); return
        }
        current = track
        position = startAt > 0 ? startAt : 0
        duration = Double(track.duration)
        ready = false
        endedFired = false
        artwork = nil
        statsLastPos = nil   // new track: next observer tick re-seeds the baseline
        // Applied once the item reaches `.readyToPlay` (seeking before then is unreliable).
        pendingSeek = startAt > 0 ? startAt : nil

        activateSession()
        let item = AVPlayerItem(url: url)
        installLevelTap(on: item)
        player.replaceCurrentItem(with: item)
        player.play()
        isPlaying = true
        loadArtwork(track)
        updateNowPlaying()
        NSLog("[playback] play \"%@\" (%@)", track.title, url.host ?? "?")
    }

    /// Attach the FFT audio tap to the item's audio track (async load) so the equalizer gets
    /// real levels. Best-effort: on any failure the equalizer falls back to decorative motion.
    private func installLevelTap(on item: AVPlayerItem) {
        let asset = item.asset
        Task { [weak self, weak item] in
            guard let tracks = try? await asset.loadTracks(withMediaType: .audio),
                  let audio = tracks.first,
                  let self, let item else { return }
            if let mix = makeLevelAudioMix(track: audio, processor: self.levelProcessor) {
                await MainActor.run { item.audioMix = mix }
            }
        }
    }

    /// Immediately stop the old item and show a loading placeholder for the next selection
    /// (so old audio never lingers while the new stream resolves over the network).
    func beginLoading(title: String, uploader: String, thumbnail: String, duration dur: Int) {
        player.replaceCurrentItem(with: nil)
        isPlaying = false
        ready = false
        endedFired = false
        position = 0
        duration = Double(dur)
        artwork = nil
        current = Track(id: "", title: title, uploader: uploader, duration: dur,
                        url: "", streamURL: "", thumbnail: thumbnail, ok: false, error: nil)
        updateNowPlaying()
    }

    private func handleEnded() {
        guard !endedFired else { return }
        endedFired = true
        onEnded?()
    }

    func togglePlayPause() { isPlaying ? pause() : resume() }

    func pause() {
        player.pause()
        isPlaying = false
        updateNowPlaying()
    }

    func resume() {
        guard current != nil else { return }
        activateSession()
        player.play()
        isPlaying = true
        updateNowPlaying()
    }

    func seek(to seconds: Double) {
        let t = CMTime(seconds: max(0, seconds), preferredTimescale: 600)
        statsLastPos = nil   // don't count the jump as listened time
        player.seek(to: t) { [weak self] _ in
            DispatchQueue.main.async {
                guard let self else { return }
                self.position = seconds
                self.updateNowPlaying()
            }
        }
    }

    func skip(_ delta: Double) { seek(to: position + delta) }

    // MARK: - Audio session

    private func configureAudioSession() {
        let s = AVAudioSession.sharedInstance()
        try? s.setCategory(.playback, mode: .default)
        NotificationCenter.default.addObserver(
            self, selector: #selector(handleInterruption(_:)),
            name: AVAudioSession.interruptionNotification, object: s)
    }

    private func activateSession() {
        try? AVAudioSession.sharedInstance().setActive(true)
    }

    @objc private func handleInterruption(_ note: Notification) {
        guard let info = note.userInfo,
              let raw = info[AVAudioSessionInterruptionTypeKey] as? UInt,
              let type = AVAudioSession.InterruptionType(rawValue: raw) else { return }
        switch type {
        case .began:
            pause()
        case .ended:
            if let optRaw = info[AVAudioSessionInterruptionOptionKey] as? UInt,
               AVAudioSession.InterruptionOptions(rawValue: optRaw).contains(.shouldResume) {
                resume()
            }
        @unknown default: break
        }
    }

    // MARK: - Player observation

    private func observePlayer() {
        NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime, object: nil, queue: .main
        ) { [weak self] _ in
            NSLog("[playback] track ended (AVPlayer)")
            self?.handleEnded()
        }

        timeObserver = player.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.5, preferredTimescale: 600),
            queue: .main
        ) { [weak self] time in
            guard let self else { return }
            // Trust metadata `duration`; some googlevideo m4a mis-report ~2× via AVPlayer.
            let p = time.seconds
            self.position = self.duration > 0 ? min(p, self.duration) : p
            // Listen-time: count only real forward audio progress (observer fires
            // every 0.5s on .main). Pauses freeze the position; seeks and track
            // changes reset statsLastPos or exceed the clamp — none of them count.
            if self.isPlaying, let last = self.statsLastPos {
                let d = self.position - last
                if d > 0 && d <= 0.75 { StatsStore.shared.tick(d) }
            }
            self.statsLastPos = self.position
            self.updateNowPlaying()
            // Advance at the real (metadata) end, since AVPlayer's end fires late for the 2×
            // mis-reported items.
            if self.duration > 0, p >= self.duration - 0.3, self.isPlaying {
                NSLog("[playback] track ended (metadata @%.0fs)", self.duration)
                self.player.pause()
                self.handleEnded()
            }
        }

        // KVO callbacks fire off the main thread; hop to main before touching @Published.
        statusObs = player.observe(\.currentItem?.status, options: [.new]) { [weak self] p, _ in
            let status = p.currentItem?.status
            let dur = p.currentItem?.duration.seconds
            let err = p.currentItem?.error
            DispatchQueue.main.async {
                guard let self else { return }
                if status == .readyToPlay {
                    self.ready = true
                    // Only fall back to AVPlayer's duration when metadata had none.
                    if self.duration <= 0, let d = dur, d.isFinite, d > 0 { self.duration = d }
                    // Apply a pending resume offset now that seeking is reliable.
                    if let s = self.pendingSeek { self.pendingSeek = nil; self.seek(to: s) }
                    self.updateNowPlaying()
                } else if status == .failed {
                    DebugLog.shared.log("playback",
                        "item failed: \(err.map { String(describing: $0) } ?? "unknown error")")
                }
            }
        }

        rateObs = player.observe(\.timeControlStatus, options: [.new]) { [weak self] p, _ in
            let playing = (p.timeControlStatus == .playing)
            DispatchQueue.main.async { self?.isPlaying = playing }
        }
    }

    // MARK: - Now Playing / remote commands

    private func updateNowPlaying() {
        guard let t = current else { return }
        var info: [String: Any] = [
            MPMediaItemPropertyTitle: t.title,
            MPMediaItemPropertyArtist: t.uploader,
            MPMediaItemPropertyPlaybackDuration: duration > 0 ? duration : Double(t.duration),
            MPNowPlayingInfoPropertyElapsedPlaybackTime: position,
            MPNowPlayingInfoPropertyPlaybackRate: isPlaying ? 1.0 : 0.0,
        ]
        if let art = artwork { info[MPMediaItemPropertyArtwork] = art }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }

    private func loadArtwork(_ track: Track) {
        guard let url = track.thumbnailURL else { return }
        URLSession.shared.dataTask(with: url) { [weak self] data, _, _ in
            guard let self, let data, let raw = UIImage(data: data) else { return }
            let img = raw.squareCropped()   // YouTube thumbs are 16:9; lock screen wants 1:1
            let art = MPMediaItemArtwork(boundsSize: img.size) { _ in img }
            DispatchQueue.main.async {
                guard self.current?.id == track.id else { return }
                self.artwork = art
                self.updateNowPlaying()
            }
        }.resume()
    }

    private func configureRemoteCommands() {
        let c = MPRemoteCommandCenter.shared()
        c.playCommand.addTarget { [weak self] _ in self?.resume(); return .success }
        c.pauseCommand.addTarget { [weak self] _ in self?.pause(); return .success }
        c.togglePlayPauseCommand.addTarget { [weak self] _ in self?.togglePlayPause(); return .success }
        // Lock-screen / Control-Center / AirPods next & previous (not skip-15s).
        c.skipForwardCommand.isEnabled = false
        c.skipBackwardCommand.isEnabled = false
        c.nextTrackCommand.isEnabled = true
        c.previousTrackCommand.isEnabled = true
        c.nextTrackCommand.addTarget { [weak self] _ in self?.onNext?(); return .success }
        c.previousTrackCommand.addTarget { [weak self] _ in self?.onPrevious?(); return .success }
        c.changePlaybackPositionCommand.addTarget { [weak self] event in
            guard let self, let e = event as? MPChangePlaybackPositionCommandEvent
            else { return .commandFailed }
            self.seek(to: e.positionTime)
            return .success
        }
    }
}
