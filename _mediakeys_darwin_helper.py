"""
macOS media-key helper — runs as its own process (spawned by mediakeys.py).

Why a subprocess: MPRemoteCommandCenter delivers command events on the main
GCD queue, which only drains when the process's MAIN thread runs the Cocoa
run loop. The TUI's main thread belongs to Textual's asyncio loop, so an
in-process integration silently never receives events. Same philosophy as
the mpv daemon: isolate the OS integration behind a line protocol.

stdin  ← JSON lines {title, artist, duration, position, is_playing}
stdout → event lines: toggle_pause | next | previous | stop
Parent death = stdin EOF → clean exit.
"""

import json
import sys
import threading

from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
from MediaPlayer import (
    MPMediaItemPropertyArtist,
    MPMediaItemPropertyPlaybackDuration,
    MPMediaItemPropertyTitle,
    MPNowPlayingInfoCenter,
    MPNowPlayingInfoPropertyElapsedPlaybackTime,
    MPNowPlayingInfoPropertyPlaybackRate,
    MPRemoteCommandHandlerStatusSuccess,
)
from PyObjCTools import AppHelper

app = NSApplication.sharedApplication()
app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)   # no Dock icon

_PLAYING, _PAUSED = 1, 2   # MPNowPlayingPlaybackState


def _emit(event):
    sys.stdout.write(event + '\n')
    sys.stdout.flush()


def _handler(event):
    def h(_evt):
        _emit(event)
        return MPRemoteCommandHandlerStatusSuccess
    return h


cc = None


def _wire_commands():
    global cc
    from MediaPlayer import MPRemoteCommandCenter
    cc = MPRemoteCommandCenter.sharedCommandCenter()
    cc.playCommand().addTargetWithHandler_(_handler('toggle_pause'))
    cc.pauseCommand().addTargetWithHandler_(_handler('toggle_pause'))
    cc.togglePlayPauseCommand().addTargetWithHandler_(_handler('toggle_pause'))
    cc.nextTrackCommand().addTargetWithHandler_(_handler('next'))
    cc.previousTrackCommand().addTargetWithHandler_(_handler('previous'))
    cc.stopCommand().addTargetWithHandler_(_handler('stop'))


def _apply_state(st):
    info = {
        MPMediaItemPropertyTitle: st.get('title') or '',
        MPMediaItemPropertyArtist: st.get('artist') or '',
        MPMediaItemPropertyPlaybackDuration: float(st.get('duration') or 0),
        MPNowPlayingInfoPropertyElapsedPlaybackTime: float(st.get('position') or 0),
        MPNowPlayingInfoPropertyPlaybackRate: 1.0 if st.get('is_playing') else 0.0,
    }
    center = MPNowPlayingInfoCenter.defaultCenter()
    center.setNowPlayingInfo_(info)
    center.setPlaybackState_(_PLAYING if st.get('is_playing') else _PAUSED)


def _stdin_loop():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            st = json.loads(line)
        except ValueError:
            continue
        AppHelper.callAfter(_apply_state, st)
    AppHelper.callAfter(app.terminate_, None)   # parent gone → exit


_wire_commands()
threading.Thread(target=_stdin_loop, daemon=True).start()
AppHelper.runEventLoop()
