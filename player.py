r"""
player.py — Audio playback backend (mpv with IPC, fallback to ffplay).

mpv runs in --idle mode; URLs loaded via IPC 'loadfile'. A single event-loop
thread owns all I/O to avoid lock contention. The byte channel to mpv is
platform-specific (a transport):
  - Windows : named pipe  \\.\pipe\<name>   (PeekNamedPipe + readline)
  - Unix    : AF_UNIX socket  <tmpdir>/<name>.sock  (select + recv)
The mpv daemon / loadfile / observe-property model is identical on every OS.
"""

import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import queue

# ── Platform branch ───────────────────────────────────────────────────────────
# Unique per-process endpoint so each run talks to the mpv IT started, never a
# stale --idle daemon from a prior run/crash.
_IS_WINDOWS = os.name == 'nt'
_PID = os.getpid()
# The endpoint name also carries a per-RUN nonce. The pid alone wasn't unique:
# the updater re-execs in place, so the new run has the SAME pid, collides with
# the daemon the old one left behind, and that orphan then lives forever. The
# nonce separates the two, and _sweep_orphans() below uses the pid still in the
# name to decide whether a daemon's owner is gone.
_RUN_NONCE = f'{os.getpid()}-{int(time.time() * 1000) % 100000:05d}'

# Consecutive send() timeouts before the IPC is declared dead (→ recovery rebuilds
# the whole mpv+IPC). Control/loadfile commands are local mpv ops answered instantly
# regardless of network, so a single 5s no-response means the socket is genuinely
# gone — not transient. With App Nap suppressed, healthy sends never time out.
_IPC_DEAD_AFTER_TIMEOUTS = 1

if _IS_WINDOWS:
    import ctypes
    import msvcrt
    _kernel32 = ctypes.windll.kernel32
    _IPC_ARG = f'ytm-tui-{_RUN_NONCE}'            # mpv creates \\.\pipe\<name>
    _CONNECT_TARGET = r'\\.\pipe' + '\\' + _IPC_ARG
else:
    import socket
    import select
    import tempfile

    def _unix_socket_path():
        """Pick a writable, short dir for the AF_UNIX socket.

        Prefer /tmp — it's short, so it stays under the AF_UNIX ~104-char path
        limit (macOS $TMPDIR can be long). But /tmp isn't writable everywhere:
        on **Termux/Android** there is no writable /tmp at all, only $TMPDIR
        under the app's private prefix. Fall back to $TMPDIR /
        tempfile.gettempdir() so mpv IPC (and thus transport controls) works on
        the phone instead of failing to create the socket.
        """
        name = f'ytm-tui-{_RUN_NONCE}.sock'
        candidates = []
        if os.path.isdir('/tmp') and os.access('/tmp', os.W_OK):
            candidates.append('/tmp')
        env_tmp = os.environ.get('TMPDIR')
        if env_tmp:
            candidates.append(env_tmp)
        candidates.append(tempfile.gettempdir())
        for d in candidates:
            try:
                if d and os.path.isdir(d) and os.access(d, os.W_OK):
                    return os.path.join(d, name)
            except OSError:
                continue
        return os.path.join(tempfile.gettempdir(), name)

    # mpv creates this socket file on launch; Python connects to the same path.
    _IPC_ARG = _unix_socket_path()
    _CONNECT_TARGET = _IPC_ARG


# The nonce group is optional: daemons started before it existed are named
# ytm-tui-<pid> and still need cleaning up.
_ENDPOINT_RE = re.compile(r'--input-ipc-server=\S*?ytm-tui-(\d+)(?:-(\d+))?')


def _pid_alive(pid):
    if _IS_WINDOWS:
        SYNCHRONIZE = 0x00100000
        h = _kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if h:
            _kernel32.CloseHandle(h)
            return True
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # alive, just not ours
    except OSError:
        return True          # unknown — err on the side of leaving it be


def _running_mpv():
    """[(pid, command line)] for every live mpv. Best effort: an OS that won't
    tell us returns nothing and the sweep simply does nothing."""
    try:
        if _IS_WINDOWS:
            out = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 "Get-CimInstance Win32_Process -Filter \"Name='mpv.exe'\" | "
                 "ForEach-Object { \"$($_.ProcessId) $($_.CommandLine)\" }"],
                capture_output=True, text=True, timeout=10).stdout
        else:
            out = subprocess.run(['ps', '-axo', 'pid=,args='],
                                 capture_output=True, text=True,
                                 timeout=10).stdout
    except Exception:
        return []
    rows = []
    for line in out.splitlines():
        line = line.strip()
        head, _, rest = line.partition(' ')
        if head.isdigit() and 'ytm-tui-' in rest:
            rows.append((int(head), rest))
    return rows


def _sweep_orphans():
    """Kill mpv daemons this app left behind.

    `--idle=yes` means a daemon outlives its parent, and nothing in the OS ties
    the two together: a crash, a `kill -9`, a closed terminal or an in-place
    re-exec all orphan one, and it keeps running — holding audio devices and
    publishing its own entry in the system's now-playing list. They accumulate
    for weeks.

    Only daemons whose endpoint name carries a pid that is GONE are killed
    (plus our own pid with a different nonce — that's the re-exec case). A
    second copy of the app running right now owns a live pid, so its daemon is
    left alone. Never a pattern kill: every pid here came out of our own
    endpoint name."""
    killed = 0
    for pid, args in _running_mpv():
        m = _ENDPOINT_RE.search(args)
        if not m:
            continue
        owner, nonce = int(m.group(1)), m.group(2) or ''
        if f'{owner}-{nonce}' == _RUN_NONCE:
            continue                        # this run's own daemon
        if owner != _PID and _pid_alive(owner):
            continue                        # another live instance — hands off
        try:
            if _IS_WINDOWS:
                subprocess.run(['taskkill', '/PID', str(pid), '/F'],
                               capture_output=True, timeout=10)
            else:
                os.kill(pid, signal.SIGTERM)
            killed += 1
        except Exception:
            pass
    return killed


_media_controls_ok = None


def _supports_media_controls(exe):
    """Whether this mpv knows --media-controls (0.37+). An mpv that doesn't
    EXITS on the unknown option instead of ignoring it, which would mean no
    audio at all — so it's probed once, cheaply, rather than assumed."""
    global _media_controls_ok
    if _media_controls_ok is None:
        try:
            r = subprocess.run([exe, '--media-controls=no', '--version'],
                               capture_output=True, timeout=10)
            _media_controls_ok = r.returncode == 0
        except Exception:
            _media_controls_ok = False
    return _media_controls_ok


def install_hint():
    """The command that installs mpv on THIS OS (for every user-facing message)."""
    if sys.platform == 'darwin':
        return 'brew install mpv'
    if _IS_WINDOWS:
        return 'winget install --id shinchiro.mpv -e'
    return 'sudo apt install mpv   (or your distro\'s package manager)'


def _backend_dirs(tool):
    """
    Where `tool` ('mpv' / 'ffplay') lands when it isn't on PATH.

    Installers routinely put mpv somewhere PATH never hears about: winget and
    scoop only extend the PATH of *new* processes, and the Windows mpv installers
    don't touch PATH at all (`C:\\Program Files\\MPV Player\\mpv.exe` is a real
    case). Entries may contain a single `*`; order is most-likely-first.
    """
    home = os.path.expanduser('~')
    if _IS_WINDOWS:
        exe = tool + '.exe'
        local = os.environ.get('LOCALAPPDATA', os.path.join(home, 'AppData', 'Local'))
        pf = os.environ.get('ProgramFiles', r'C:\Program Files')
        pf86 = os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
        return [
            os.path.join(local, 'Microsoft', 'WinGet', 'Links', exe),
            os.path.join(pf, '*mpv*', exe),            # 'MPV Player', 'mpv', 'mpv.net'
            os.path.join(pf86, '*mpv*', exe),
            os.path.join(pf, '*mpv*', 'bin', exe),
            os.path.join(pf, 'ffmpeg', 'bin', exe),
            os.path.join(local, 'Programs', '*mpv*', exe),
            os.path.join(home, 'scoop', 'shims', exe),
            os.path.join(home, 'scoop', 'apps', '*', 'current', exe),
            r'C:\ProgramData\chocolatey\bin\%s' % exe,
            os.path.join(local, 'Microsoft', 'WinGet', 'Packages', '*', exe),
            os.path.join(local, 'Microsoft', 'WinGet', 'Packages', '*', 'bin', exe),
            r'C:\mpv\%s' % exe,
            r'C:\ffmpeg\bin\%s' % exe,
        ]
    paths = [
        f'/opt/homebrew/bin/{tool}',          # Apple Silicon Homebrew
        f'/usr/local/bin/{tool}',             # Intel Homebrew, hand-built
        f'/opt/local/bin/{tool}',             # MacPorts
        f'/usr/bin/{tool}',
        f'/snap/bin/{tool}',
        os.path.join(home, '.local', 'bin', tool),
    ]
    if sys.platform == 'darwin' and tool == 'mpv':
        paths.append('/Applications/mpv.app/Contents/MacOS/mpv')
    return paths


_backend_exe_cache = {}


def find_backend_exe(tool):
    """
    Absolute path to 'mpv' / 'ffplay', or None. PATH first, then _backend_dirs().

    Only hits are cached: a miss is cheap (a handful of stats) and must not
    outlive the user installing mpv while the app is open.
    """
    if not tool:
        return None
    cached = _backend_exe_cache.get(tool)
    if cached:
        return cached
    found = shutil.which(tool)
    if not found:
        for pattern in _backend_dirs(tool):
            if '*' in pattern:
                import glob
                hits = sorted(p for p in glob.glob(pattern) if os.access(p, os.X_OK))
            else:
                hits = [pattern] if os.access(pattern, os.X_OK) else []
            if hits:
                found = hits[0]
                break
    if found:
        _backend_exe_cache[tool] = found
    return found


def detect_backend():
    """Return 'mpv' or 'ffplay', whichever can be found (see find_backend_exe)."""
    if find_backend_exe('mpv'):
        return 'mpv'
    if find_backend_exe('ffplay'):
        return 'ffplay'
    raise RuntimeError(
        f'No audio backend found. Install mpv ({install_hint()}) '
        'or ffmpeg (for ffplay).'
    )


def _find_ytdlp():
    """
    Locate a yt-dlp executable for mpv's ytdl_hook.

    mpv runs as a separate process and resolves yt-dlp from its own PATH. When
    this app runs inside a virtualenv, yt-dlp lives next to the venv's Python and
    is NOT on the system PATH, so mpv can't stream YouTube. Prefer the binary
    beside our interpreter, then fall back to PATH.
    """
    exe = 'yt-dlp.exe' if _IS_WINDOWS else 'yt-dlp'
    cand = os.path.join(os.path.dirname(sys.executable), exe)
    if os.path.isfile(cand):
        return cand
    # venvs on Unix sometimes keep scripts in a Scripts/bin sibling
    return shutil.which('yt-dlp')


# ── IPC transports (platform-specific byte channel to mpv) ────────────────────

def _peek_pipe(fd):
    """Return number of bytes available to read from a Windows named pipe fd."""
    try:
        handle = msvcrt.get_osfhandle(fd)
        avail = ctypes.c_ulong(0)
        _kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(avail), None)
        return avail.value
    except Exception:
        return 0


class _WinPipeTransport:
    """Windows named-pipe transport (PeekNamedPipe + blocking readline)."""

    def __init__(self):
        self._conn = None
        self._fd   = None

    def connect(self, retries=30, delay=0.15):
        for _ in range(retries):
            try:
                self._conn = open(_CONNECT_TARGET, 'r+b', buffering=0)
                self._fd   = self._conn.fileno()
                return True
            except OSError:
                time.sleep(delay)
        return False

    def write(self, data):
        self._conn.write(data)

    def poll_line(self):
        """Return one complete line (without newline) if data is ready, else None."""
        if _peek_pipe(self._fd) <= 0:
            return None
        raw = b''
        while True:
            ch = self._conn.read(1)
            if not ch or ch == b'\n':
                break
            raw += ch
        return raw or None

    def close(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            self._fd   = None


class _UnixSocketTransport:
    """macOS/Linux AF_UNIX socket transport (select + recv with line buffering)."""

    def __init__(self):
        self._sock = None
        self._buf  = b''

    def connect(self, retries=30, delay=0.15):
        for _ in range(retries):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(_CONNECT_TARGET)
                self._sock = s
                return True
            except OSError:
                time.sleep(delay)
        return False

    def write(self, data):
        self._sock.sendall(data)

    def _pop_line(self):
        nl = self._buf.find(b'\n')
        if nl >= 0:
            line, self._buf = self._buf[:nl], self._buf[nl + 1:]
            return line
        return None

    def poll_line(self):
        """Return one complete line (without newline) if available, else None."""
        line = self._pop_line()
        if line is not None:
            return line
        try:
            readable, _, _ = select.select([self._sock], [], [], 0)
            if readable:
                chunk = self._sock.recv(4096)
                if chunk:
                    self._buf += chunk
                    return self._pop_line()
        except OSError:
            pass
        return None

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        # mpv usually removes its socket on exit; clean up best-effort just in case.
        try:
            if os.path.exists(_CONNECT_TARGET):
                os.unlink(_CONNECT_TARGET)
        except Exception:
            pass


def _make_transport():
    return _WinPipeTransport() if _IS_WINDOWS else _UnixSocketTransport()


class _MpvIPC:
    """
    Single-thread event loop over a platform transport to mpv's JSON IPC.

    One thread owns ALL reads and writes:
      - drains an outbound command queue, then polls the transport for a line
    Main thread enqueues commands and waits on threading.Event for responses.
    """

    def __init__(self):
        self._transport = None
        self._running   = False
        self._loop_th   = None

        self._cmd_q     = queue.Queue()          # bytes to write
        self._req_lock  = threading.Lock()
        self._req_id    = 0
        self._pending   = {}                     # req_id -> {'evt', 'result'}

        # Health: set once the socket stops responding (send timeout) or a
        # transport write fails. Sticky — recovery replaces the whole instance.
        self._dead            = False
        self._consec_timeouts = 0

        self.position      = 0.0
        self.duration      = 0.0
        self.on_end        = None
        self._pending_seek = 0.0     # absolute seek to apply once the file loads

    # ── Connection ─────────────────────────────────────────────────────────

    def connect(self, retries=30, delay=0.15):
        transport = _make_transport()
        if not transport.connect(retries=retries, delay=delay):
            return False
        self._transport = transport
        self._running = True
        self._loop_th = threading.Thread(
            target=self._loop, daemon=True, name='mpv-ipc'
        )
        self._loop_th.start()
        self._fire(['observe_property', 1, 'time-pos'])
        self._fire(['observe_property', 2, 'duration'])
        return True

    def disconnect(self):
        self._running = False
        if self._transport:
            self._transport.close()
            self._transport = None
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
                    self._transport.write(data)
                except queue.Empty:
                    break
                except Exception:
                    if not self._running:
                        return
                    # Broken pipe / closed socket while still running: mpv is
                    # gone or the socket is dead. Flag it so a control call or
                    # the poll backstop triggers recovery instead of hanging.
                    self._dead = True

            # 2. Non-blocking: read a line if one is ready
            try:
                raw = self._transport.poll_line()
            except Exception:
                raw = None
            if raw:
                try:
                    self._dispatch(json.loads(raw.decode()))
                except Exception:
                    pass
            else:
                time.sleep(0.01)

    def _dispatch(self, obj):
        evt = obj.get('event')
        if evt == 'file-loaded':
            # Apply a pending resume seek now that the file is decodable.
            # Use _fire (non-blocking) — we're on the loop thread; send() would
            # deadlock waiting for a response this same thread must read.
            if self._pending_seek > 0:
                self._fire(['seek', self._pending_seek, 'absolute'])
                self._pending_seek = 0.0
        elif evt == 'property-change':
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
        """Enqueue command and block until response arrives (or timeout).

        A real response is always a truthy dict, so `result is None` is an
        unambiguous failure (timeout / disconnect). Enough of those in a row
        marks the IPC dead so the app can rebuild it instead of freezing on
        every subsequent 5s wait."""
        if not self._running:
            return None
        with self._req_lock:
            self._req_id += 1
            req_id = self._req_id
        entry = {'evt': threading.Event(), 'result': None}
        self._pending[req_id] = entry
        msg = (json.dumps({'command': cmd, 'request_id': req_id}) + '\n').encode()
        self._cmd_q.put(msg)
        entry['evt'].wait(timeout)
        self._pending.pop(req_id, None)
        result = entry.get('result')
        if result is None:
            self._consec_timeouts += 1
            if self._consec_timeouts >= _IPC_DEAD_AFTER_TIMEOUTS:
                self._dead = True
        else:
            self._consec_timeouts = 0
        return result

    def is_healthy(self):
        return self._running and not self._dead

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
        if backend:
            self.backend = backend
        else:
            try:
                self.backend = detect_backend()
            except RuntimeError:
                # No mpv/ffplay — the app still runs (search/browse work);
                # playback stays disabled with a clear message instead of crashing.
                self.backend = None
        # The exact executable to spawn — not the bare name: mpv is often
        # installed somewhere this process's PATH doesn't cover.
        self.backend_exe = find_backend_exe(self.backend) or self.backend
        self.cookies_file = cookies_file
        self._proc        = None
        self._ipc         = None
        self._lock        = threading.Lock()
        self._start_lock  = threading.Lock()   # prevents concurrent _ensure_mpv_running
        self._paused      = False
        self._current_url = None
        self._on_end_cb   = None
        # An --idle daemon outlives a crashed/killed/re-exec'd parent, so clear
        # out whatever earlier runs left behind. Off the main thread: it shells
        # out to ps, and nothing here blocks startup.
        threading.Thread(target=_sweep_orphans, daemon=True).start()
        # Last line of defence for a clean interpreter exit that skipped quit().
        atexit.register(self._shutdown_mpv)

    def set_on_end(self, callback):
        self._on_end_cb = callback
        if self._ipc:
            self._ipc.on_end = callback

    # ── mpv daemon management ─────────────────────────────────────────────

    def _ensure_mpv_running(self):
        if self.backend != 'mpv':
            return
        with self._start_lock:
            proc_alive = bool(self._proc and self._proc.poll() is None)
            ipc_alive  = self._ipc is not None and self._ipc.is_healthy()
            if proc_alive and ipc_alive:
                return
            # Proc died OR the socket went stale (send marked the IPC dead):
            # tear the whole backend down and rebuild a fresh _MpvIPC (new loop
            # thread) below, so even the normal next-track path self-heals.
            if self._proc or self._ipc:
                self._shutdown_mpv()
            cmd = [
                self.backend_exe, '--no-video', '--ytdl=yes',
                f'--input-ipc-server={_IPC_ARG}',
                '--idle=yes', '--really-quiet',
                # Bound the network so a stalled load can't wedge the mpv daemon forever
                # (ytdl_hook runs synchronously on mpv's main thread). --network-timeout is
                # mpv's own; socket-timeout is passed through to yt-dlp below.
                '--network-timeout=15',
                # CRITICAL: without --no-terminal, mpv reads the controlling
                # terminal/TTY for its own keybindings and STEALS keystrokes from the
                # Textual UI — the UI renders fine (clock ticks) but no key is ever
                # delivered. Cross-platform (TTY on macOS/Linux, console on Windows).
                # We drive mpv only over the IPC socket, so it must never touch the
                # terminal. stdin=DEVNULL below is the belt-and-suspenders half.
                '--no-terminal',
            ]
            # mpv publishes its OWN entry to the system now-playing list, named
            # after the IPC socket ("mpv-55554944..."). We already publish a
            # proper one via mediakeys.py, so mpv's is pure clutter — and it
            # answers the media keys directly, behind the app's back.
            if _supports_media_controls(self.backend_exe):
                cmd.append('--media-controls=no')
            ytdlp = _find_ytdlp()
            if ytdlp:
                cmd.append(f'--script-opts=ytdl_hook-ytdl_path={ytdlp}')
            # One --ytdl-raw-options carrying every yt-dlp passthrough (socket-timeout bounds
            # extraction; cookiefile when set). Passing the flag twice would drop the first.
            raw = ['socket-timeout=15']
            if self.cookies_file and os.path.isfile(self.cookies_file):
                raw.append(f'cookiefile={self.cookies_file}')
            cmd.append('--ytdl-raw-options=' + ','.join(raw))
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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

    def play(self, url, start=0.0):
        """Play url. start>0 resumes playback at that absolute offset (seconds)."""
        if not self.backend:
            raise RuntimeError(
                f'No audio backend. Install mpv ({install_hint()}) or ffmpeg.'
            )
        with self._lock:
            if self.backend == 'mpv':
                self._play_mpv(url, start)
            else:
                self._play_ffplay(url, start)
            self._current_url = url
            self._paused = False

    def _play_mpv(self, url, start=0.0):
        self._ensure_mpv_running()
        if self._ipc:
            self._ipc.position = 0.0
            self._ipc.duration = 0.0
            # Schedule the resume seek to fire on the 'file-loaded' event.
            self._ipc._pending_seek = float(start) if start and start > 0 else 0.0
            self._ipc.command('loadfile', url, 'replace')
            # mpv's 'pause' property persists across loadfile. Without this, a
            # track loaded after a pause (e.g. 'next' while paused) stays paused
            # while the UI shows it playing. Force-resume on every explicit play.
            self._ipc.set_property('pause', False)
        else:
            # IPC unavailable — launch mpv directly with the URL. Without IPC we
            # get no position/seek/pause, but at least keep auto-advance working
            # by watching the process exit and firing on_end (like ffplay does).
            self._shutdown_mpv()
            cmd = [self.backend_exe, '--no-video', '--ytdl=yes', '--really-quiet',
                   '--network-timeout=15', '--no-terminal', url]
            if _supports_media_controls(self.backend_exe):
                cmd.append('--media-controls=no')   # see the daemon spawn above
            if start and start > 0:
                cmd.append(f'--start=+{int(start)}')
            ytdlp = _find_ytdlp()
            if ytdlp:
                cmd.append(f'--script-opts=ytdl_hook-ytdl_path={ytdlp}')
            raw = ['socket-timeout=15']
            if self.cookies_file and os.path.isfile(self.cookies_file):
                raw.append(f'cookiefile={self.cookies_file}')
            cmd.append('--ytdl-raw-options=' + ','.join(raw))
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._proc = proc

            def _watch():
                proc.wait()
                if proc is self._proc and self._on_end_cb:
                    self._on_end_cb()
            threading.Thread(target=_watch, daemon=True).start()

    def _spawn_ffplay(self, target, start=0.0):
        """Launch ffplay on a (local path or stream) URL and watch for end."""
        # -nostdin + stdin=DEVNULL so ffplay never reads terminal keys either.
        args = [self.backend_exe, '-nodisp', '-autoexit', '-nostdin',
                '-loglevel', 'quiet']
        if start and start > 0:
            args += ['-ss', str(int(start))]   # ffplay seeks before -i
        args.append(target)
        proc = subprocess.Popen(
            args, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._proc = proc

        def _watch():
            proc.wait()
            # Only auto-advance on a natural finish — not when this proc was
            # superseded by the next track or an explicit stop (proc replaced).
            if proc is self._proc and self._on_end_cb:
                self._on_end_cb()
        threading.Thread(target=_watch, daemon=True).start()

    def _play_ffplay(self, url, start=0.0):
        self._terminate_proc()   # supersede any previous ffplay (lock-free)
        if os.path.isfile(url):
            self._spawn_ffplay(url, start)
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
            'socket_timeout': 15, 'retries': 1,   # don't hang forever on a stalled fetch
        }
        if self.cookies_file and os.path.isfile(self.cookies_file):
            opts['cookiefile'] = self.cookies_file

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            stream_url = info.get('url') or url
        self._spawn_ffplay(stream_url, start)

    def _terminate_proc(self):
        """Stop the current child process (ffplay / direct-launch mpv). Lock-free.

        Sets self._proc = None first so any watcher thread sees it was superseded
        and does NOT fire on_end (prevents an auto-advance cascade)."""
        proc = self._proc
        self._proc = None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _stop_locked(self):
        if self.backend == 'mpv' and self._ipc:
            self._ipc.command('stop')
            self._ipc.position = 0.0
            self._ipc.duration = 0.0
        else:
            self._terminate_proc()
        self._paused = False
        self._current_url = None

    def stop(self):
        with self._lock:
            self._stop_locked()

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

    def ipc_healthy(self):
        """False only when an existing mpv IPC has stopped responding (stale
        socket / hung daemon). True for a fresh/no IPC (nothing to recover) or
        a responsive one; True for ffplay (no IPC to recover)."""
        if self.backend != 'mpv':
            return True
        ipc = self._ipc
        return ipc is None or ipc.is_healthy()

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
