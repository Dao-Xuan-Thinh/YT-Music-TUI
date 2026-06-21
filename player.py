"""
player.py — Audio playback backend (mpv with IPC, fallback to ffplay).

mpv runs in --idle mode; URLs loaded via IPC 'loadfile'.
A single event-loop thread owns all pipe I/O to avoid FileIO lock contention:
  PeekNamedPipe  → non-blocking check for data
  readline loop  → read one JSON line when data is available
  send queue     → main thread enqueues commands; loop drains queue
"""

import ctypes
import json
import msvcrt
import os
import queue
import shutil
import subprocess
import threading
import time


def detect_backend():
    """Return 'mpv' or 'ffplay' depending on what's on PATH."""
    if shutil.which('mpv'):
        return 'mpv'
    if shutil.which('ffplay'):
        return 'ffplay'
    raise RuntimeError(
        'No audio backend found. Install mpv (recommended) or ffmpeg (for ffplay).'
    )


# ── mpv IPC ───────────────────────────────────────────────────────────────────

# Unique pipe name per process so each app run talks to the mpv IT started,
# never a stale --idle daemon left over from a prior run/crash. On Windows two
# mpv processes can't own the same named pipe; reusing a fixed name made the IPC
# connect to a leftover (paused) mpv → no audio.
_PIPE_ARG  = f'ytm-tui-{os.getpid()}'
_PIPE_PATH = r'\\.\pipe' + '\\' + _PIPE_ARG
_kernel32  = ctypes.windll.kernel32


def _peek_pipe(fd):
    """Return number of bytes available to read from Windows named pipe fd."""
    try:
        handle = msvcrt.get_osfhandle(fd)
        avail = ctypes.c_ulong(0)
        _kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(avail), None)
        return avail.value
    except Exception:
        return 0


class _MpvIPC:
    """
    Single-thread event loop for mpv's named pipe IPC.

    One thread owns ALL reads and writes:
      - polls PeekNamedPipe (non-blocking) before each read
      - drains an outbound command queue before each poll
    Main thread enqueues commands and waits on threading.Event for responses.
    """

    def __init__(self):
        self._conn      = None
        self._fd        = None
        self._running   = False
        self._loop_th   = None

        self._cmd_q     = queue.Queue()          # bytes to write
        self._req_lock  = threading.Lock()
        self._req_id    = 0
        self._pending   = {}                     # req_id -> {'evt', 'result'}

        self.position   = 0.0
        self.duration   = 0.0
        self.on_end     = None

    # ── Connection ─────────────────────────────────────────────────────────

    def connect(self, retries=30, delay=0.15):
        for _ in range(retries):
            try:
                self._conn = open(_PIPE_PATH, 'r+b', buffering=0)
                self._fd   = self._conn.fileno()
                self._running = True
                self._loop_th = threading.Thread(
                    target=self._loop, daemon=True, name='mpv-ipc'
                )
                self._loop_th.start()
                self._fire(['observe_property', 1, 'time-pos'])
                self._fire(['observe_property', 2, 'duration'])
                return True
            except OSError:
                time.sleep(delay)
        return False

    def disconnect(self):
        self._running = False
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            self._fd   = None
        for entry in list(self._pending.values()):
            entry['evt'].set()
        self._pending.clear()

    # ── Event loop (single thread owns all I/O) ───────────────────────────

    def _loop(self):
        while self._running:
            # 1. Drain outbound queue
            while True:
                try:
                    data = self._cmd_q.get_nowait()
                    self._conn.write(data)
                except queue.Empty:
                    break
                except Exception:
                    if not self._running:
                        return

            # 2. Non-blocking check: data available?
            if _peek_pipe(self._fd) > 0:
                try:
                    raw = self._readline()
                    if raw:
                        self._dispatch(json.loads(raw.decode()))
                except Exception:
                    pass
            else:
                time.sleep(0.01)

    def _readline(self):
        raw = b''
        while True:
            ch = self._conn.read(1)
            if not ch or ch == b'\n':
                break
            raw += ch
        return raw

    def _dispatch(self, obj):
        evt = obj.get('event')
        if evt == 'property-change':
            name = obj.get('name')
            data = obj.get('data')
            if data is not None:
                if name == 'time-pos':
                    self.position = float(data)
                elif name == 'duration':
                    self.duration = float(data)
        elif evt == 'end-file':
            self.position = 0.0
            self.duration = 0.0
            reason = obj.get('reason', '')
            # Only advance to the next track on natural end-of-file.
            # 'stop' fires when loadfile replaces the current track —
            # triggering on_end there causes the fast-cycling cascade bug.
            if reason in ('eof', 'error') and self.on_end:
                self.on_end()
        elif 'request_id' in obj:
            req_id = obj['request_id']
            entry = self._pending.get(req_id)
            if entry:
                entry['result'] = obj
                entry['evt'].set()

    # ── Public API ─────────────────────────────────────────────────────────

    def _fire(self, cmd):
        """Enqueue command without waiting for a response."""
        with self._req_lock:
            self._req_id += 1
            req_id = self._req_id
        msg = (json.dumps({'command': cmd, 'request_id': req_id}) + '\n').encode()
        self._cmd_q.put(msg)

    def send(self, cmd, timeout=5.0):
        """Enqueue command and block until response arrives (or timeout)."""
        with self._req_lock:
            self._req_id += 1
            req_id = self._req_id
        entry = {'evt': threading.Event(), 'result': None}
        self._pending[req_id] = entry
        msg = (json.dumps({'command': cmd, 'request_id': req_id}) + '\n').encode()
        self._cmd_q.put(msg)
        entry['evt'].wait(timeout)
        self._pending.pop(req_id, None)
        return entry.get('result')

    def set_property(self, prop, value):
        self.send(['set_property', prop, value])

    def get_property(self, prop):
        res = self.send(['get_property', prop])
        if res and res.get('error') == 'success':
            return res.get('data')
        return None

    def command(self, *args):
        self.send(list(args))


# ── Player ────────────────────────────────────────────────────────────────────

class Player:
    """
    Unified audio player.  mpv runs as a persistent daemon (--idle=yes).
    URLs are played via IPC 'loadfile' so IPC is always responsive.
    Falls back to ffplay when mpv is not installed.
    """

    def __init__(self, backend=None, cookies_file=None):
        self.backend      = backend or detect_backend()
        self.cookies_file = cookies_file
        self._proc        = None
        self._ipc         = None
        self._lock        = threading.Lock()
        self._start_lock  = threading.Lock()   # prevents concurrent _ensure_mpv_running
        self._paused      = False
        self._current_url = None
        self._on_end_cb   = None

    def set_on_end(self, callback):
        self._on_end_cb = callback
        if self._ipc:
            self._ipc.on_end = callback

    # ── mpv daemon management ─────────────────────────────────────────────

    def _ensure_mpv_running(self):
        with self._start_lock:
            if self._proc and self._proc.poll() is None:
                return
            cmd = [
                'mpv', '--no-video', '--ytdl=yes',
                f'--input-ipc-server={_PIPE_ARG}',
                '--idle=yes', '--really-quiet',
            ]
            if self.cookies_file and os.path.isfile(self.cookies_file):
                cmd.append(f'--ytdl-raw-options=cookiefile={self.cookies_file}')
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._ipc = _MpvIPC()
            self._ipc.on_end = self._on_end_cb
            if not self._ipc.connect():
                self._ipc = None

    def _shutdown_mpv(self):
        if self._ipc:
            self._ipc.disconnect()
            self._ipc = None
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    # ── Playback ──────────────────────────────────────────────────────────

    def play(self, url):
        if self.backend == 'mpv':
            self._play_mpv(url)
        else:
            self.stop()
            self._play_ffplay(url)
        self._current_url = url
        self._paused = False

    def _play_mpv(self, url):
        self._ensure_mpv_running()
        if self._ipc:
            self._ipc.position = 0.0
            self._ipc.duration = 0.0
            self._ipc.command('loadfile', url, 'replace')
        else:
            # IPC unavailable — launch mpv directly with URL
            self._shutdown_mpv()
            cmd = ['mpv', '--no-video', '--ytdl=yes', '--really-quiet', url]
            if self.cookies_file and os.path.isfile(self.cookies_file):
                cmd.append(f'--ytdl-raw-options=cookiefile={self.cookies_file}')
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    def _play_ffplay(self, url):
        if os.path.isfile(url):
            def _run_local():
                self._proc = subprocess.Popen(
                    ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', url],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self._proc.wait()
                if self._on_end_cb:
                    self._on_end_cb()
            threading.Thread(target=_run_local, daemon=True).start()
            return

        import yt_dlp

        class _Silent:
            def debug(self, m): pass
            def info(self, m): pass
            def warning(self, m): pass
            def error(self, m): pass

        opts = {
            'quiet': True, 'no_warnings': True, 'logger': _Silent(),
            'format': 'bestaudio/best',
        }
        if self.cookies_file and os.path.isfile(self.cookies_file):
            opts['cookiefile'] = self.cookies_file

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            stream_url = info.get('url') or url

        def _run():
            self._proc = subprocess.Popen(
                ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', stream_url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._proc.wait()
            if self._on_end_cb:
                self._on_end_cb()

        threading.Thread(target=_run, daemon=True).start()

    def stop(self):
        with self._lock:
            if self.backend == 'mpv' and self._ipc:
                self._ipc.command('stop')
                self._ipc.position = 0.0
                self._ipc.duration = 0.0
            elif self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                self._proc = None
            self._paused = False
            self._current_url = None

    def quit(self):
        """Fully shut down the mpv daemon."""
        self._shutdown_mpv()
        self._paused = False
        self._current_url = None

    # ── Controls ──────────────────────────────────────────────────────────

    def pause(self):
        if self._paused:
            return
        self._paused = True
        if self.backend == 'mpv' and self._ipc:
            self._ipc.set_property('pause', True)

    def resume(self):
        if not self._paused:
            return
        self._paused = False
        if self.backend == 'mpv' and self._ipc:
            self._ipc.set_property('pause', False)

    def toggle_pause(self):
        if self._paused:
            self.resume()
        else:
            self.pause()

    def seek(self, delta_seconds):
        if self.backend == 'mpv' and self._ipc:
            self._ipc.command('seek', delta_seconds, 'relative')

    def set_volume(self, pct):
        pct = max(0, min(100, int(pct)))
        if self.backend == 'mpv' and self._ipc:
            self._ipc.set_property('volume', pct)

    # ── Status ────────────────────────────────────────────────────────────

    def get_position(self):
        if self.backend == 'mpv' and self._ipc:
            return self._ipc.position
        return 0.0

    def get_duration(self):
        if self.backend == 'mpv' and self._ipc:
            return self._ipc.duration
        return 0.0

    def is_playing(self):
        return self._proc is not None and self._proc.poll() is None

    def is_paused(self):
        return self._paused

    @property
    def current_url(self):
        return self._current_url


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys

    backend = detect_backend()
    print(f'Backend: {backend}')

    test_url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
    print(f'Playing: {test_url}')
    print('(you should hear audio)\n')

    p = Player()
    p.play(test_url)

    for i in range(20):
        time.sleep(2)
        pos = p.get_position()
        dur = p.get_duration()
        print(f't={2*(i+1):>2}s  pos={pos:.1f}s  dur={dur:.1f}s  playing={p.is_playing()}')
        if pos > 1.0:
            break

    if p.get_position() > 0:
        print('\nPausing 2s...')
        p.pause()
        time.sleep(2)
        print('Resuming...')
        p.resume()
        time.sleep(2)
        print('Seeking +30s...')
        p.seek(30)
        time.sleep(2)
        print(f'Position after seek: {p.get_position():.1f}s')

    print('\nStopping.')
    p.quit()
    print('Done.')
