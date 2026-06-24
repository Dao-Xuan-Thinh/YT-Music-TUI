"""
updater.py — self-update via git.

The app is distributed as a git clone (Windows / macOS / Linux), so updating is
just `git pull` plus a dependency refresh. This module wraps that behind a few
safe helpers the TUI calls from background threads:

  available_backend()  → is this a real git checkout with git on PATH?
  check_for_update()    → fetch + count how many commits we're behind upstream.
  apply_update()        → ff-only pull, then pip install if requirements changed.
  restart()            → re-exec the interpreter so the new code takes effect.

Everything is best-effort: on any error we return a structured result instead of
raising, so a missing remote / offline machine / non-git install degrades to a
quiet "couldn't check" rather than breaking the app.
"""

import os
import subprocess
import sys

_REPO_DIR = os.path.dirname(os.path.abspath(__file__))

# Hide the console window that subprocess would flash on Windows.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def _git(*args, timeout=30):
    """Run a git command in the repo. Returns (ok, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ['git', '-C', _REPO_DIR, *args],
            capture_output=True, text=True, timeout=timeout,
            creationflags=_NO_WINDOW,
        )
        return proc.returncode == 0, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return False, '', 'git not found on PATH'
    except subprocess.TimeoutExpired:
        return False, '', 'git command timed out'
    except Exception as exc:  # pragma: no cover - defensive
        return False, '', str(exc)


def available_backend():
    """True if this is a git checkout and git is callable (else self-update is off)."""
    if not os.path.isdir(os.path.join(_REPO_DIR, '.git')):
        return False
    ok, _, _ = _git('rev-parse', '--is-inside-work-tree', timeout=10)
    return ok


def current_revision():
    """Short hash of the current HEAD (or '' if unavailable)."""
    ok, out, _ = _git('rev-parse', '--short', 'HEAD', timeout=10)
    return out if ok else ''


def _upstream():
    """The configured upstream ref (e.g. 'origin/master'), or '' if none."""
    ok, out, _ = _git('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}',
                      timeout=10)
    return out if ok else ''


def current_branch():
    """Name of the checked-out branch (or '' if detached / unavailable)."""
    ok, out, _ = _git('rev-parse', '--abbrev-ref', 'HEAD', timeout=10)
    return out if ok and out != 'HEAD' else ''


def list_branches():
    """Short names of branches available on origin (e.g. ['master', 'test'])."""
    ok, out, _ = _git('branch', '-r', timeout=15)
    if not ok:
        return []
    names = []
    for line in out.splitlines():
        line = line.strip()
        if not line or '->' in line:        # skip 'origin/HEAD -> origin/master'
            continue
        if line.startswith('origin/'):
            name = line[len('origin/'):]
            if name and name not in names:
                names.append(name)
    return names


def check_for_update():
    """
    Fetch from the remote and report how far behind upstream we are.

    Returns a dict:
      {'available': bool, 'behind': int, 'ahead': int,
       'upstream': str, 'error': str | None}
    """
    result = {'available': False, 'behind': 0, 'ahead': 0,
              'upstream': '', 'error': None}

    if not available_backend():
        result['error'] = 'not a git checkout'
        return result

    upstream = _upstream()
    if not upstream:
        result['error'] = 'no upstream configured (not cloned from a remote?)'
        return result
    result['upstream'] = upstream

    ok, _, err = _git('fetch', '--quiet', timeout=60)
    if not ok:
        result['error'] = err or 'git fetch failed'
        return result

    # Commits we're behind / ahead of upstream.
    ok, out, err = _git('rev-list', '--left-right', '--count', f'HEAD...{upstream}',
                        timeout=15)
    if not ok:
        result['error'] = err or 'could not compare with upstream'
        return result
    try:
        ahead_s, behind_s = out.split()
        result['ahead'] = int(ahead_s)
        result['behind'] = int(behind_s)
    except ValueError:
        result['error'] = 'unexpected git output'
        return result

    result['available'] = result['behind'] > 0
    return result


def _read_requirements_hash():
    path = os.path.join(_REPO_DIR, 'requirements.txt')
    try:
        with open(path, 'rb') as f:
            import hashlib
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ''


def _refresh_deps():
    """pip install -r requirements.txt. Returns an error string, or '' on success."""
    try:
        proc = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '-r',
             os.path.join(_REPO_DIR, 'requirements.txt'), '--quiet'],
            capture_output=True, text=True, timeout=300,
            creationflags=_NO_WINDOW,
        )
        if proc.returncode != 0:
            return proc.stderr.strip() or proc.stdout.strip() or 'pip install failed'
        return ''
    except Exception as exc:  # pragma: no cover - defensive
        return str(exc)


def apply_update():
    """
    Pull the latest code (fast-forward only) and refresh deps if they changed.

    Returns a dict:
      {'ok': bool, 'updated': bool, 'deps_changed': bool,
       'message': str, 'error': str | None}
    """
    result = {'ok': False, 'updated': False, 'deps_changed': False,
              'message': '', 'error': None}

    if not available_backend():
        result['error'] = 'not a git checkout'
        return result

    # Refuse to clobber local edits — a fast-forward pull would abort anyway, but
    # this gives a clearer message.
    ok, out, _ = _git('status', '--porcelain', timeout=15)
    if ok and out.strip():
        result['error'] = ('you have local changes — commit or stash them first, '
                           'then update')
        return result

    before = _read_requirements_hash()

    ok, out, err = _git('pull', '--ff-only', timeout=120)
    if not ok:
        result['error'] = err or out or 'git pull failed'
        return result

    result['ok'] = True
    result['updated'] = 'Already up to date' not in out
    after = _read_requirements_hash()
    result['deps_changed'] = bool(before) and before != after

    if result['updated'] and result['deps_changed']:
        err = _refresh_deps()
        if err:
            result['error'] = ('updated, but dependency install failed — run '
                               '"pip install -r requirements.txt" manually: ' + err)

    if result['updated']:
        result['message'] = 'Updated' + (' (dependencies refreshed)'
                                         if result['deps_changed'] else '')
    else:
        result['message'] = 'Already up to date'
    return result


def switch_branch(target):
    """
    Switch to another branch and fast-forward it.

    Fetches first, checks out `target` (creating a local tracking branch from
    origin/<target> if it doesn't exist locally), ff-pulls, and refreshes deps if
    requirements.txt changed across the switch.

    Returns a dict:
      {'ok': bool, 'switched': bool, 'branch': str, 'deps_changed': bool,
       'message': str, 'error': str | None}
    """
    result = {'ok': False, 'switched': False, 'branch': '', 'deps_changed': False,
              'message': '', 'error': None}

    if not available_backend():
        result['error'] = 'not a git checkout'
        return result

    target = (target or '').strip()
    if not target:
        result['error'] = 'no branch specified'
        return result

    if current_branch() == target:
        result['ok'] = True
        result['branch'] = target
        result['message'] = f'Already on {target}'
        return result

    # Refuse to clobber local edits — a checkout would either fail or drag them
    # onto the other branch.
    ok, out, _ = _git('status', '--porcelain', timeout=15)
    if ok and out.strip():
        result['error'] = ('you have local changes — commit or stash them first, '
                           'then switch branches')
        return result

    before = _read_requirements_hash()

    ok, _, err = _git('fetch', '--quiet', timeout=60)
    if not ok:
        result['error'] = err or 'git fetch failed'
        return result

    # Local branch already there? Plain switch; otherwise create it tracking origin.
    local_ok, _, _ = _git('rev-parse', '--verify', '--quiet',
                          f'refs/heads/{target}', timeout=10)
    if local_ok:
        ok, out, err = _git('switch', target, timeout=30)
    else:
        ok, out, err = _git('switch', '-c', target, '--track',
                            f'origin/{target}', timeout=30)
    if not ok:
        result['error'] = err or out or f'could not switch to {target}'
        return result

    result['switched'] = True
    result['branch'] = target

    # Fast-forward to the remote tip (no-op if already current).
    ok, out, err = _git('pull', '--ff-only', timeout=120)
    if not ok:
        result['ok'] = True   # we did switch; just couldn't pull
        result['message'] = f'Switched to {target} (pull skipped: {err or out})'
        return result

    result['ok'] = True
    after = _read_requirements_hash()
    result['deps_changed'] = bool(before) and before != after

    if result['deps_changed']:
        dep_err = _refresh_deps()
        if dep_err:
            result['error'] = ('switched, but dependency install failed — run '
                               '"pip install -r requirements.txt" manually: ' + dep_err)

    result['message'] = ('Switched to ' + target
                         + (' (dependencies refreshed)' if result['deps_changed'] else ''))
    return result


def restart():
    """Re-exec the current interpreter so freshly-pulled code is loaded."""
    os.execv(sys.executable, [sys.executable, *sys.argv])


if __name__ == '__main__':
    print(f'Repo: {_REPO_DIR}')
    print(f'git checkout: {available_backend()}  revision: {current_revision()}')
    print('Checking for update…')
    print(check_for_update())
