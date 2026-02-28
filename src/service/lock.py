from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional


class FileLock:
    """Simple cross-process lock using a lock file.

    - Tries to create lock file with O_CREAT|O_EXCL semantics.
    - Waits with polling until acquired or timeout.
    - Writes PID into the lock file for visibility.
    - On context exit, removes the lock file.

    Note: This is a best-effort lightweight lock for coordinating service writes.
    """

    def __init__(self, path: Path, *, timeout: float = 10.0, poll_interval: float = 0.1) -> None:
        self.path = Path(path)
        self.timeout = float(timeout)
        self.poll_interval = float(poll_interval)
        self._fd: Optional[int] = None

    def acquire(self) -> None:
        deadline = time.time() + self.timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        last_err: Optional[BaseException] = None
        while time.time() < deadline:
            try:
                # On Windows + POSIX, os.O_EXCL ensures exclusive creation
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                self._fd = fd
                os.write(fd, str(os.getpid()).encode("utf-8"))
                os.fsync(fd)
                return
            except FileExistsError as e:  # already locked
                last_err = e
                time.sleep(self.poll_interval)
            except Exception as e:  # unexpected, but retry a bit
                last_err = e
                time.sleep(self.poll_interval)
        # Timeout
        raise TimeoutError(f"failed to acquire lock: {self.path}: {last_err}")

    def release(self) -> None:
        try:
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except Exception:
                    pass
            if self.path.exists():
                try:
                    os.remove(self.path)
                except Exception:
                    # best-effort
                    pass
        finally:
            self._fd = None

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.release()

