"""
bootstrap.py — first-boot dependency setup.

main.py imports this *before* any third-party module, so a fresh clone on a new
machine runs with plain `python main.py` and nothing else: anything listed in
requirements.txt that isn't installed is pip-installed into the right
interpreter, then the process re-execs so the new packages are importable.

An audio backend (mpv, or ffplay from ffmpeg) can't come from pip, so when
neither is on PATH this prints the command for this OS and — on a terminal —
offers to run the platform package manager.

Stdlib only: it has to work before anything is installed. Skip it with
`YTM_NO_BOOTSTRAP=1` or `--no-bootstrap` (packaged installs, CI, offline boxes).

  ensure()         → deps + backend, the one call main.py makes
  missing_report() → what's absent, without installing anything
"""

import os
import sys

# shutil / subprocess / sysconfig / importlib.metadata are imported inside the
# functions that need them: on a healthy install this module does almost nothing
# and must not add import time to every launch.

_ROOT = os.path.dirname(os.path.abspath(__file__))
_REQ_FILE = os.path.join(_ROOT, 'requirements.txt')
_STAMP = os.path.join(_ROOT, '.deps-stamp')

# Re-exec guard: set on the child so a failed install can't loop forever.
_RAN_ENV = 'YTM_BOOTSTRAP_RAN'


def _no_window():
    """Hide the console window subprocess would flash on Windows."""
    import subprocess
    return subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def _say(msg):
    """
    Progress goes to stderr: stdout may be a pipe someone is parsing.

    Everything printed here stays ASCII on purpose. This runs before Textual
    owns the terminal, and a plain print() of '—' or '✓' raises
    UnicodeEncodeError on a Windows console still on a legacy code page.
    """
    print(f'[setup] {msg}', file=sys.stderr, flush=True)


# ── stamp: skip the whole check on an install we already verified ─────────────
# The metadata lookup below costs ~20 ms, which is real next to this app's
# startup, so a healthy install records what it verified and skips. The key
# covers the interpreter and requirements.txt, so a pull that adds a dependency
# (or a different python) re-checks; find_spec() catches a venv wiped by hand.

def _stamp_key():
    try:
        st = os.stat(_REQ_FILE)
    except OSError:
        return ''
    return f'{sys.executable}|{sys.version_info[:2]}|{int(st.st_mtime)}|{st.st_size}'


def _stamp_ok():
    key = _stamp_key()
    if not key:
        return False
    try:
        with open(_STAMP, encoding='utf-8') as fh:
            if fh.read().strip() != key:
                return False
    except OSError:
        return False
    import importlib.util
    try:
        return importlib.util.find_spec('textual') is not None
    except Exception:
        return False


def _write_stamp():
    try:
        with open(_STAMP, 'w', encoding='utf-8') as fh:
            fh.write(_stamp_key())
    except OSError:
        pass          # read-only checkout: we just re-check next launch


# ── requirements.txt ──────────────────────────────────────────────────────────

def _dist_name(spec):
    """'yt-dlp>=2024.1.0' → 'yt-dlp'. Extras and version pins dropped."""
    for i, ch in enumerate(spec):
        if ch in '[<>=!~ (;':
            return spec[:i].strip()
    return spec.strip()


def _marker_applies(marker):
    """
    Evaluate the small subset of PEP 508 markers this project uses
    (`sys_platform` / `platform_system` equality). `packaging` isn't importable
    yet, so anything else is treated as applicable — such a requirement is also
    forced optional by _requirements(), so a wrong guess can never block boot.
    """
    env = {'sys_platform': sys.platform, 'platform_system': _platform_system()}
    for op in ('==', '!='):
        for key, value in env.items():
            if marker.startswith(key):
                rest = marker[len(key):].strip()
                if not rest.startswith(op):
                    continue
                wanted = rest[len(op):].strip().strip('\'"')
                return (value == wanted) if op == '==' else (value != wanted)
    return None          # unrecognised


def _platform_system():
    return {'darwin': 'Darwin', 'win32': 'Windows'}.get(sys.platform, 'Linux')


def _requirements():
    """
    Parse requirements.txt → [(dist_name, spec_line, optional)] for this OS.

    A comment line starting with `# optional` marks every entry below it as
    nice-to-have: it's still installed, but a missing or unbuildable one only
    warns instead of holding up the app (that's the media-key section).
    """
    reqs, optional = [], False
    try:
        with open(_REQ_FILE, encoding='utf-8') as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []

    for raw in lines:
        line = raw.strip()
        if line.startswith('#'):
            if line[1:].strip().lower().startswith('optional'):
                optional = True
            continue
        if not line:
            continue
        line = line.split(' #')[0].strip()          # inline comment
        spec, _, marker = line.partition(';')
        spec, marker = spec.strip(), marker.strip()
        opt = optional
        if marker:
            applies = _marker_applies(marker)
            if applies is False:
                continue                            # not for this OS
            if applies is None:
                opt = True                          # unknown marker → never fatal
        name = _dist_name(spec)
        if name:
            reqs.append((name, spec, opt))
    return reqs


def missing_report():
    """(required, optional) dist names that aren't installed."""
    from importlib.metadata import PackageNotFoundError, version

    required, opt = [], []
    for name, _spec, is_opt in _requirements():
        try:
            version(name)
        except PackageNotFoundError:
            (opt if is_opt else required).append(name)
        except Exception:
            pass                                    # unreadable metadata: assume ok
    return required, opt


# ── where to install ──────────────────────────────────────────────────────────

def _in_venv():
    return sys.prefix != getattr(sys, 'base_prefix', sys.prefix)


def _externally_managed():
    """
    PEP 668: Homebrew / Debian / Arch pythons refuse to be pip-installed into.
    Those need a virtualenv, which is also the friendlier answer — we never
    touch a system site-packages.

    A venv built *from* such a python still reports its base stdlib here, so —
    like pip itself — the marker only counts outside a virtualenv.
    """
    if _in_venv():
        return False
    import sysconfig
    for key in ('stdlib', 'purelib'):
        try:
            path = sysconfig.get_path(key)
        except Exception:
            continue
        if path and os.path.exists(os.path.join(path, 'EXTERNALLY-MANAGED')):
            return True
    return False


def _venv_python(venv_dir):
    sub = 'Scripts' if os.name == 'nt' else 'bin'
    exe = 'python.exe' if os.name == 'nt' else 'python'
    return os.path.join(venv_dir, sub, exe)


def _project_venv():
    """An existing project venv (either spelling), else where we'd make one."""
    for name in ('.venv', 'venv'):
        candidate = os.path.join(_ROOT, name)
        if os.path.isfile(_venv_python(candidate)):
            return candidate, True
    return os.path.join(_ROOT, '.venv'), False


def _ensure_venv():
    """Return a project-venv interpreter, creating the venv if needed."""
    import subprocess
    venv_dir, exists = _project_venv()
    if not exists:
        _say(f'creating a virtualenv in {os.path.basename(venv_dir)} ...')
        try:
            subprocess.run([sys.executable, '-m', 'venv', venv_dir],
                           check=True, creationflags=_no_window())
        except Exception as exc:
            _say(f'could not create a virtualenv: {exc}')
            return None
    python = _venv_python(venv_dir)
    return python if os.path.isfile(python) else None


def _pip(python, *args):
    """Run pip in `python`. Output is left visible - installs are slow."""
    import subprocess
    cmd = [python, '-m', 'pip', '--disable-pip-version-check', *args]
    try:
        return subprocess.run(cmd, creationflags=_no_window()).returncode == 0
    except Exception as exc:
        _say(f'pip failed to start: {exc}')
        return False


def _have_pip(python):
    if _pip(python, '--version'):
        return True
    _say('pip is missing - bootstrapping it with ensurepip ...')
    import subprocess
    try:
        subprocess.run([python, '-m', 'ensurepip', '--upgrade'],
                       check=True, creationflags=_no_window())
    except Exception:
        return False
    return _pip(python, '--version')


# ── audio backend (not a pip package) ─────────────────────────────────────────

def _backend_present():
    import shutil
    return bool(shutil.which('mpv') or shutil.which('ffplay'))


def _backend_installer():
    """(human command, argv to run) for this OS, or (hint, None) if unknown."""
    import shutil
    if sys.platform == 'darwin':
        if shutil.which('brew'):
            return 'brew install mpv', ['brew', 'install', 'mpv']
        return 'brew install mpv  (install Homebrew first: https://brew.sh)', None
    if sys.platform == 'win32':
        if shutil.which('winget'):
            # shinchiro.mpv is the long-standing mpv build in the winget repo.
            return ('winget install --id shinchiro.mpv -e',
                    ['winget', 'install', '--id', 'shinchiro.mpv', '-e',
                     '--accept-package-agreements', '--accept-source-agreements'])
        if shutil.which('scoop'):
            return 'scoop install mpv', ['scoop', 'install', 'mpv']
        return 'install mpv from https://mpv.io/installation/ (or: scoop install mpv)', None
    for mgr, argv in (
        ('apt-get', ['sudo', 'apt-get', 'install', '-y', 'mpv']),
        ('pacman', ['sudo', 'pacman', '-S', '--noconfirm', 'mpv']),
        ('dnf', ['sudo', 'dnf', 'install', '-y', 'mpv']),
        ('zypper', ['sudo', 'zypper', 'install', '-y', 'mpv']),
    ):
        if shutil.which(mgr):
            return ' '.join(argv), argv
    return 'install mpv with your package manager', None


def _interactive():
    try:
        return sys.stdin.isatty() and sys.stderr.isatty()
    except Exception:
        return False


def _ask(question):
    try:
        return input(f'[setup] {question} [Y/n] ').strip().lower() in ('', 'y', 'yes')
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return False


def ensure_backend():
    """Warn (and optionally install) when there's nothing to play audio with."""
    if _backend_present():
        return True
    human, argv = _backend_installer()
    _say('no audio backend found - mpv (preferred) or ffmpeg/ffplay is required.')
    if argv and _interactive() and _ask(f'run `{human}` now?'):
        import subprocess
        try:
            subprocess.run(argv, check=True)
        except Exception as exc:
            _say(f'that failed ({exc}) - install it by hand: {human}')
        else:
            # winget/scoop put mpv on the PATH of *new* shells only.
            if _backend_present():
                _say('mpv installed ok')
                return True
            _say('installed - restart the terminal so mpv is on your PATH.')
            return False
    else:
        _say(f'install it with:  {human}')
    return False


# ── entry point ───────────────────────────────────────────────────────────────

def ensure():
    """
    The one call main.py makes: install missing packages (re-execing if they
    had to go into a new virtualenv), then check the audio backend. Returns
    True when the app can import its dependencies; False when something is
    still missing (main.py then fails on the import, as it did before this
    existed).
    """
    if os.environ.get('YTM_NO_BOOTSTRAP') or '--no-bootstrap' in sys.argv:
        return True
    ok = _ensure_deps()
    if ok:
        ensure_backend()
    return ok


def _ensure_deps():
    if _stamp_ok():
        return True

    required, optional = missing_report()
    if not required and not optional:
        _write_stamp()
        return True

    if os.environ.get(_RAN_ENV):
        # We already installed and re-exec'd once; don't spin.
        if required:
            _say('still missing after install: ' + ', '.join(required))
            _say(f'install by hand:  {sys.executable} -m pip install -r "{_REQ_FILE}"')
        return not required

    names = ', '.join(required + optional)
    _say(f'first run on this machine - {len(required) + len(optional)} package(s) '
         f'to install: {names}')

    # Install into this interpreter when that's allowed; a system Python that
    # refuses (PEP 668) gets a project virtualenv instead, and we re-exec into it.
    python = sys.executable
    if not _in_venv() and _externally_managed():
        python = _ensure_venv() or sys.executable

    if not _have_pip(python):
        _say('no pip available - install the dependencies by hand: '
             f'{python} -m pip install -r "{_REQ_FILE}"')
        return not required

    ok = _pip(python, 'install', '-r', _REQ_FILE)
    if not ok and optional:
        # One unbuildable optional wheel (the media-key bindings on an odd
        # platform) must not stop the app: retry with just the required ones.
        _say('full install failed - retrying without the optional extras ...')
        specs = [spec for _n, spec, is_opt in _requirements() if not is_opt]
        ok = _pip(python, 'install', *specs)
    if not ok:
        _say('install failed - see the pip output above.')
        return not required

    _say('dependencies installed ok, restarting ...')
    env = dict(os.environ, **{_RAN_ENV: '1'})
    script = os.path.join(_ROOT, 'main.py')
    args = [python, script, *sys.argv[1:]]
    try:
        # execv keeps the terminal attached; Windows needs the wait-and-exit form.
        if os.name == 'nt':
            import subprocess
            sys.exit(subprocess.run(args, env=env).returncode)
        os.execve(python, args, env)
    except SystemExit:
        raise
    except Exception as exc:
        _say(f'could not restart ({exc}) - run the app again to pick up the new packages.')
        return False
    return True


if __name__ == '__main__':
    import shutil
    required, optional = missing_report()
    print('missing (required):', ', '.join(required) or 'none')
    print('missing (optional):', ', '.join(optional) or 'none')
    print('audio backend     :',
          shutil.which('mpv') or shutil.which('ffplay') or 'NONE - ' + _backend_installer()[0])
    print('interpreter       :', sys.executable, '(venv)' if _in_venv() else '(system)')
