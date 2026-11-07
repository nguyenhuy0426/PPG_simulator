"""
instance_lock.py — one simulator process per user.

Two copies would fight over the MCP4725 DACs on I2C and over the BLE GATT
server, so main.py takes an exclusive flock(2) before it touches either.

The lock file is the one scripts/launch_ppg_simulator.sh already locks:
$XDG_STATE_HOME/ppg-simulator/app.lock (default ~/.local/state/...).  One file
means one lock, whichever way the app was started: the desktop icon, the
systemd user service, scripts/deploy_and_run.sh, or `.venv/bin/python main.py`
typed in a terminal.  The state directory is derived from HOME alone, so it is
the same in a desktop session, under the systemd user manager and over SSH;
XDG_RUNTIME_DIR is not, because it is missing under `su` and in some SSH and
cron contexts.

flock locks belong to an open file description.  The launcher locks fd 9 and
exec()s Python with that descriptor still open and locked.  Opening the file
again would create a second description, and its flock would conflict with the
launcher's own lock, so the launcher exports PPG_APP_LOCK_FD=9 and this module
locks that descriptor instead.  flock on a description that already holds the
lock succeeds immediately.

The kernel drops the lock when the last descriptor on it closes, which includes
a crash or SIGKILL; there is no stale PID file to clean up.
"""

import errno
import fcntl
import os
from pathlib import Path

# Exit status for "another instance holds the lock".  75 is EX_TEMPFAIL from
# sysexits.h.  packaging/linux/ppg-simulator.service.in lists it in
# RestartPreventExitStatus=, so systemd does not retry a lock conflict.
EXIT_ALREADY_RUNNING = 75

LOCK_FD_ENV = "PPG_APP_LOCK_FD"

# Keeps the descriptor (and so the lock) open until the process exits.
_held_fd = None


class AlreadyRunning(RuntimeError):
    def __init__(self, path, pid):
        self.path = path
        self.pid = pid
        holder = f"process {pid}" if pid else "another process"
        super().__init__(f"Another PPG simulator instance is already running ({holder} holds {path})")


def lock_path():
    state_home = os.environ.get("XDG_STATE_HOME") or os.path.join(Path.home(), ".local", "state")
    return Path(state_home) / "ppg-simulator" / "app.lock"


def _inherited_fd(path):
    """The launcher's descriptor on `path`, or None if there is no usable one."""
    value = os.environ.pop(LOCK_FD_ENV, None)  # not for child processes
    if value is None:
        return None
    try:
        fd = int(value)
        held, wanted = os.fstat(fd), os.stat(path)
    except (ValueError, OSError):
        return None
    if (held.st_dev, held.st_ino) != (wanted.st_dev, wanted.st_ino):
        return None
    return fd


def _read_pid(fd):
    try:
        text = os.pread(fd, 32, 0).decode("ascii", "replace").strip()
    except OSError:
        return None
    return int(text) if text.isdigit() else None


def acquire():
    """Take the per-user lock or raise AlreadyRunning.  Idempotent."""
    global _held_fd
    if _held_fd is not None:
        return lock_path()
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = _inherited_fd(path)
    if fd is None:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    # The launcher's descriptor is inheritable.  A child holding it would keep
    # the lock alive after this process dies.
    os.set_inheritable(fd, False)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
            os.close(fd)
            raise
        pid = _read_pid(fd)
        os.close(fd)
        raise AlreadyRunning(path, pid) from None
    # The PID is only a hint for the conflict message; the lock is the truth.
    try:
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{os.getpid()}\n".encode("ascii"), 0)
    except OSError:
        pass
    _held_fd = fd
    return path
