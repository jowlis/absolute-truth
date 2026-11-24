"""One run at a time: a lock file that the operating system releases if the process dies.

Two runs writing the same knowledge base at once would tangle the history chain, so
run.py (started by hand, by the dashboard or by the autopilot) holds this lock while it
runs. The lock is an OS file lock, not just a file that exists: if a run crashes or the
computer restarts, the lock is gone and the next run can start.
"""

import os
from pathlib import Path


class AlreadyRunning(Exception):
    """Another process holds the lock."""


class RunLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, "a+b")
        try:
            _lock(f)
        except OSError:
            f.close()
            raise AlreadyRunning(f"Another run is in progress (lock: {self.path}).") from None
        self._file = f
        return self

    def __exit__(self, *exc):
        if self._file:
            try:
                _unlock(self._file)
            finally:
                self._file.close()
                self._file = None
        return False


if os.name == "nt":
    import msvcrt

    def _lock(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
