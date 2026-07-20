"""
mediakeys.py — OS media-key + now-playing integration for the TUI.

`start(callbacks)` returns a backend or None. Callbacks (`toggle_pause`, `next`,
`previous`, `stop`) are invoked from backend threads — the app wraps them in
`call_from_thread`. Backends expose `set_now_playing(title, artist, duration,
position, is_playing)` (cheap, coalescing) and `stop()`.

Per-OS, all optional (a bare install just gets None — zero behavior change):
- macOS:  helper subprocess (pyobjc + MPRemoteCommandCenter). The Cocoa run
  loop must own the process's MAIN thread to receive command events, and ours
  belongs to Textual — so, like mpv, the integration lives in its own tiny
  process (_mediakeys_darwin_helper.py) speaking JSON lines over stdin/stdout.
- Linux:  MPRIS2 server over D-Bus via dbus-fast (pure Python), own asyncio
  loop on a daemon thread. Shows up in playerctl/GNOME/KDE media controls.
- Windows: System Media Transport Controls via the PyWinRT packages, using a
  dormant Windows.Media.Playback.MediaPlayer (documented no-hwnd desktop
  route; WinRT events arrive on thread-pool threads).
"""

import json
import os
import subprocess
import sys
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))


def start(callbacks):
    """Start the platform backend. Returns the backend or None (missing dep /
    unsupported platform / init failure) — callers treat None as 'no media
    keys' and change nothing else."""
    try:
        if sys.platform == 'darwin':
            return _DarwinBackend(callbacks)
        if sys.platform.startswith('linux'):
            return _LinuxBackend(callbacks)
        if sys.platform == 'win32':
            return _WindowsBackend(callbacks)
    except Exception:
        return None
    return None


class _Base:
    def __init__(self, callbacks):
        self._cb = callbacks
        self._last = None   # coalescing key for set_now_playing

    def _dispatch(self, event):
        cb = self._cb.get(event)
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def set_now_playing(self, title, artist, duration, position, is_playing):
        raise NotImplementedError

    def stop(self):
        pass


# ── macOS ────────────────────────────────────────────────────────────────────

class _DarwinBackend(_Base):
    def __init__(self, callbacks):
        import MediaPlayer  # noqa: F401 — probe the dep before spawning
        super().__init__(callbacks)
        helper = os.path.join(_HERE, '_mediakeys_darwin_helper.py')
        self._proc = subprocess.Popen(
            [sys.executable, helper],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1)
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        try:
            for line in self._proc.stdout:
                self._dispatch(line.strip())
        except Exception:
            pass

    def set_now_playing(self, title, artist, duration, position, is_playing):
        # Position updates every second; only title/state changes need a full
        # metadata push, but the helper handles per-line updates cheaply.
        key = (title, artist, int(duration), int(position), is_playing)
        if key == self._last:
            return
        self._last = key
        try:
            self._proc.stdin.write(json.dumps({
                'title': title, 'artist': artist, 'duration': float(duration),
                'position': float(position), 'is_playing': bool(is_playing),
            }) + '\n')
            self._proc.stdin.flush()
        except Exception:
            pass

    def stop(self):
        try:
            self._proc.stdin.close()   # EOF → helper exits its run loop
            self._proc.terminate()
        except Exception:
            pass


# ── Linux (MPRIS2) ───────────────────────────────────────────────────────────

class _LinuxBackend(_Base):
    def __init__(self, callbacks):
        from dbus_fast.service import (ServiceInterface, method,
                                       dbus_property, PropertyAccess)
        from dbus_fast import Variant
        super().__init__(callbacks)
        import asyncio
        backend = self

        class Root(ServiceInterface):
            def __init__(self):
                super().__init__('org.mpris.MediaPlayer2')

            @dbus_property(access=PropertyAccess.READ)
            def Identity(self) -> 's':                     # noqa: F821
                return 'ytm-tui'

            @dbus_property(access=PropertyAccess.READ)
            def CanQuit(self) -> 'b':                      # noqa: F821
                return False

            @dbus_property(access=PropertyAccess.READ)
            def CanRaise(self) -> 'b':                     # noqa: F821
                return False

            @dbus_property(access=PropertyAccess.READ)
            def HasTrackList(self) -> 'b':                 # noqa: F821
                return False

            @dbus_property(access=PropertyAccess.READ)
            def SupportedUriSchemes(self) -> 'as':         # noqa: F821
                return []

            @dbus_property(access=PropertyAccess.READ)
            def SupportedMimeTypes(self) -> 'as':          # noqa: F821
                return []

        class Player(ServiceInterface):
            def __init__(self):
                super().__init__('org.mpris.MediaPlayer2.Player')
                self.status = 'Stopped'
                self.meta = {}
                self.position_us = 0

            @method()
            def PlayPause(self):
                backend._dispatch('toggle_pause')

            @method()
            def Play(self):
                backend._dispatch('toggle_pause')

            @method()
            def Pause(self):
                backend._dispatch('toggle_pause')

            @method()
            def Next(self):
                backend._dispatch('next')

            @method()
            def Previous(self):
                backend._dispatch('previous')

            @method()
            def Stop(self):
                backend._dispatch('stop')

            @dbus_property(access=PropertyAccess.READ)
            def PlaybackStatus(self) -> 's':               # noqa: F821
                return self.status

            @dbus_property(access=PropertyAccess.READ)
            def Metadata(self) -> 'a{sv}':                 # noqa: F821
                return self.meta

            @dbus_property(access=PropertyAccess.READ)
            def Position(self) -> 'x':                     # noqa: F821
                return self.position_us

            @dbus_property(access=PropertyAccess.READ)
            def Rate(self) -> 'd':                         # noqa: F821
                return 1.0

            @dbus_property(access=PropertyAccess.READ)
            def MinimumRate(self) -> 'd':                  # noqa: F821
                return 1.0

            @dbus_property(access=PropertyAccess.READ)
            def MaximumRate(self) -> 'd':                  # noqa: F821
                return 1.0

            @dbus_property(access=PropertyAccess.READ)
            def Volume(self) -> 'd':                       # noqa: F821
                return 1.0

            @dbus_property(access=PropertyAccess.READ)
            def CanPlay(self) -> 'b':                      # noqa: F821
                return True

            @dbus_property(access=PropertyAccess.READ)
            def CanPause(self) -> 'b':                     # noqa: F821
                return True

            @dbus_property(access=PropertyAccess.READ)
            def CanGoNext(self) -> 'b':                    # noqa: F821
                return True

            @dbus_property(access=PropertyAccess.READ)
            def CanGoPrevious(self) -> 'b':                # noqa: F821
                return True

            @dbus_property(access=PropertyAccess.READ)
            def CanSeek(self) -> 'b':                      # noqa: F821
                return False

            @dbus_property(access=PropertyAccess.READ)
            def CanControl(self) -> 'b':                   # noqa: F821
                return True

            def push(self, title, artist, duration, position, is_playing):
                self.status = 'Playing' if is_playing else 'Paused'
                self.position_us = int(position * 1e6)
                self.meta = {
                    'mpris:trackid': Variant('o', '/org/ytmtui/track/current'),
                    'mpris:length': Variant('x', int(duration * 1e6)),
                    'xesam:title': Variant('s', title or ''),
                    'xesam:artist': Variant('as', [artist or '']),
                }
                self.emit_properties_changed(
                    {'PlaybackStatus': self.status, 'Metadata': self.meta})

        self._loop = asyncio.new_event_loop()
        self._player = Player()
        self._root = Root()
        self._ready = threading.Event()
        self._ok = False
        threading.Thread(target=self._serve, daemon=True).start()
        # If D-Bus is unreachable (no session bus), fail so start() returns None.
        self._ready.wait(5.0)
        if not self._ok:
            raise RuntimeError('mpris unavailable')

    def _serve(self):
        import asyncio
        from dbus_fast.aio import MessageBus
        asyncio.set_event_loop(self._loop)

        async def main():
            try:
                bus = await MessageBus().connect()
                bus.export('/org/mpris/MediaPlayer2', self._root)
                bus.export('/org/mpris/MediaPlayer2', self._player)
                await bus.request_name('org.mpris.MediaPlayer2.ytmtui')
                self._ok = True
            finally:
                self._ready.set()
            await asyncio.get_event_loop().create_future()   # run forever

        try:
            self._loop.run_until_complete(main())
        except Exception:
            self._ready.set()

    def set_now_playing(self, title, artist, duration, position, is_playing):
        key = (title, artist, is_playing)
        emit_meta = key != self._last
        self._last = key
        p = self._player
        if emit_meta:
            self._loop.call_soon_threadsafe(
                p.push, title, artist, duration, position, is_playing)
        else:
            # Position-only tick — no PropertiesChanged storm.
            p.position_us = int(position * 1e6)


# ── Windows (SMTC) ───────────────────────────────────────────────────────────

class _WindowsBackend(_Base):
    def __init__(self, callbacks):
        from winrt.windows.media.playback import MediaPlayer
        from winrt.windows.media import (
            SystemMediaTransportControlsButton as Btn,
            MediaPlaybackStatus, MediaPlaybackType)
        super().__init__(callbacks)
        self._Btn, self._Status, self._Type = Btn, MediaPlaybackStatus, MediaPlaybackType
        self._mp = MediaPlayer()                     # dormant; owns the SMTC
        self._mp.command_manager.is_enabled = False  # manual button wiring
        smtc = self._mp.system_media_transport_controls
        smtc.is_enabled = True
        smtc.is_play_enabled = True
        smtc.is_pause_enabled = True
        smtc.is_next_enabled = True
        smtc.is_previous_enabled = True
        smtc.is_stop_enabled = True
        self._smtc = smtc
        self._token = smtc.add_button_pressed(self._on_button)

    def _on_button(self, sender, args):
        Btn = self._Btn
        event = {Btn.PLAY: 'toggle_pause', Btn.PAUSE: 'toggle_pause',
                 Btn.NEXT: 'next', Btn.PREVIOUS: 'previous',
                 Btn.STOP: 'stop'}.get(args.button)
        if event:
            self._dispatch(event)

    def set_now_playing(self, title, artist, duration, position, is_playing):
        key = (title, artist, is_playing)
        if key == self._last:
            return
        self._last = key
        try:
            self._smtc.playback_status = (self._Status.PLAYING if is_playing
                                          else self._Status.PAUSED)
            du = self._smtc.display_updater
            du.type = self._Type.MUSIC
            du.music_properties.title = title or ''
            du.music_properties.artist = artist or ''
            du.update()
        except Exception:
            pass

    def stop(self):
        try:
            self._smtc.remove_button_pressed(self._token)
            self._smtc.is_enabled = False
        except Exception:
            pass
