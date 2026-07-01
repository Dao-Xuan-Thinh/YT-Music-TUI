import AVFoundation
import Accelerate
import QuartzCore

/// Computes a small frequency-band spectrum (RMS magnitudes) from live PCM, for the
/// now-playing equalizer. Buffers are allocated once and reused (the process callback runs
/// on a realtime audio thread, so no per-call allocation). Thread-safe snapshot via a lock.
final class AudioLevelProcessor {
    let bands: Int
    private let fftSize = 1024
    private let half = 512
    private let log2n: vDSP_Length
    private let fftSetup: FFTSetup
    private let window: UnsafeMutablePointer<Float>
    private let windowed: UnsafeMutablePointer<Float>
    private let realp: UnsafeMutablePointer<Float>
    private let imagp: UnsafeMutablePointer<Float>
    private let mags: UnsafeMutablePointer<Float>
    private var split: DSPSplitComplex

    private let lock = NSLock()
    private var _levels: [Float]
    private var _lastTime: CFTimeInterval = 0
    private var _peak: Float = 0.01   // running auto-gain reference

    init(bands: Int) {
        self.bands = bands
        log2n = vDSP_Length(log2(Double(fftSize)))
        fftSetup = vDSP_create_fftsetup(log2n, FFTRadix(kFFTRadix2))!
        window = .allocate(capacity: fftSize)
        windowed = .allocate(capacity: fftSize)
        realp = .allocate(capacity: half)
        imagp = .allocate(capacity: half)
        mags = .allocate(capacity: half)
        _levels = [Float](repeating: 0, count: bands)
        split = DSPSplitComplex(realp: realp, imagp: imagp)
        vDSP_hann_window(window, vDSP_Length(fftSize), Int32(vDSP_HANN_NORM))
    }

    deinit {
        vDSP_destroy_fftsetup(fftSetup)
        window.deallocate(); windowed.deallocate()
        realp.deallocate(); imagp.deallocate(); mags.deallocate()
    }

    /// Latest band levels (0…1) and whether they're fresh (updated recently).
    func snapshot() -> (levels: [Float], time: CFTimeInterval) {
        lock.lock(); defer { lock.unlock() }
        return (_levels, _lastTime)
    }

    /// Called from the audio thread with interleaved/mono Float PCM (we use channel 0).
    func process(samples: UnsafePointer<Float>, count: Int) {
        let n = min(count, fftSize)
        guard n > 0 else { return }
        if n < fftSize { vDSP_vclr(windowed, 1, vDSP_Length(fftSize)) }
        vDSP_vmul(samples, 1, window, 1, windowed, 1, vDSP_Length(n))

        windowed.withMemoryRebound(to: DSPComplex.self, capacity: half) { cplx in
            vDSP_ctoz(cplx, 2, &split, 1, vDSP_Length(half))
        }
        vDSP_fft_zrip(fftSetup, &split, 1, log2n, FFTDirection(FFT_FORWARD))
        vDSP_zvabs(&split, 1, mags, 1, vDSP_Length(half))

        // Group bins into log-spaced bands (skip DC), take the mean magnitude per band.
        var out = [Float](repeating: 0, count: bands)
        let usable = half - 1
        var frameMax: Float = 0
        for b in 0..<bands {
            let lo = Int(pow(Double(usable), Double(b) / Double(bands)))
            let hi = max(lo + 1, Int(pow(Double(usable), Double(b + 1) / Double(bands))))
            var sum: Float = 0, cnt: Float = 0
            var i = lo + 1
            while i <= min(hi, usable) { sum += mags[i]; cnt += 1; i += 1 }
            let v = cnt > 0 ? sum / cnt : 0
            out[b] = v
            frameMax = max(frameMax, v)
        }
        // Auto-gain: normalize against a slowly-decaying peak so bars fill nicely at any
        // absolute magnitude, then compress with sqrt for a livelier low end.
        lock.lock()
        _peak = max(frameMax, _peak * 0.92)
        let ref = max(_peak, 0.0001)
        for b in 0..<bands { out[b] = min(1, sqrt(out[b] / ref)) }
        _levels = out
        _lastTime = CACurrentMediaTime()
        lock.unlock()
    }
}

// MARK: - MTAudioProcessingTap C callbacks

private func tapInit(_ tap: MTAudioProcessingTap,
                     _ clientInfo: UnsafeMutableRawPointer?,
                     _ tapStorageOut: UnsafeMutablePointer<UnsafeMutableRawPointer?>) {
    tapStorageOut.pointee = clientInfo   // carry the processor pointer as tap storage
}

private func tapFinalize(_ tap: MTAudioProcessingTap) {
    Unmanaged<AudioLevelProcessor>.fromOpaque(MTAudioProcessingTapGetStorage(tap)).release()
}

private func tapProcess(_ tap: MTAudioProcessingTap,
                        _ numberFrames: CMItemCount,
                        _ flags: MTAudioProcessingTapFlags,
                        _ bufferListInOut: UnsafeMutablePointer<AudioBufferList>,
                        _ numberFramesOut: UnsafeMutablePointer<CMItemCount>,
                        _ flagsOut: UnsafeMutablePointer<MTAudioProcessingTapFlags>) {
    let status = MTAudioProcessingTapGetSourceAudio(tap, numberFrames, bufferListInOut,
                                                    flagsOut, nil, numberFramesOut)
    guard status == noErr else { return }
    let processor = Unmanaged<AudioLevelProcessor>
        .fromOpaque(MTAudioProcessingTapGetStorage(tap)).takeUnretainedValue()
    let abl = UnsafeMutableAudioBufferListPointer(bufferListInOut)
    guard let buf = abl.first, let data = buf.mData else { return }
    let count = Int(buf.mDataByteSize) / MemoryLayout<Float>.size
    processor.process(samples: data.assumingMemoryBound(to: Float.self), count: count)
}

/// Build an `AVAudioMix` carrying an MTAudioProcessingTap that feeds `processor`, for the
/// given audio track. Returns nil if the tap can't be created.
func makeLevelAudioMix(track: AVAssetTrack, processor: AudioLevelProcessor) -> AVAudioMix? {
    var callbacks = MTAudioProcessingTapCallbacks(
        version: kMTAudioProcessingTapCallbacksVersion_0,
        clientInfo: UnsafeMutableRawPointer(Unmanaged.passRetained(processor).toOpaque()),
        init: tapInit, finalize: tapFinalize, prepare: nil, unprepare: nil, process: tapProcess)

    var tap: MTAudioProcessingTap?
    let err = MTAudioProcessingTapCreate(kCFAllocatorDefault, &callbacks,
                                         kMTAudioProcessingTapCreationFlag_PostEffects, &tap)
    guard err == noErr, let realTap = tap else {
        // Creation failed → balance the passRetained (clientInfo) so the processor isn't leaked.
        Unmanaged<AudioLevelProcessor>.fromOpaque(callbacks.clientInfo!).release()
        return nil
    }
    let params = AVMutableAudioMixInputParameters(track: track)
    params.audioTapProcessor = realTap
    let mix = AVMutableAudioMix()
    mix.inputParameters = [params]
    return mix
}
