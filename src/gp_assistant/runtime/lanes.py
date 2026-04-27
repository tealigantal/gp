from __future__ import annotations

import os
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from threading import Lock, RLock, local

from ..core.paths import store_dir


_session_locks: dict[str, Lock] = defaultdict(Lock)
_book_thread_lock = RLock()
_book_thread_state = local()
_BOOK_LOCK_TIMEOUT_SEC = 30.0
_BOOK_LOCK_POLL_SEC = 0.05


def _book_lock_path() -> Path:
    path = store_dir() / "book" / ".reconcile.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _acquire_process_lock(path: Path) -> None:
    deadline = time.monotonic() + _BOOK_LOCK_TIMEOUT_SEC
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                payload = f"{os.getpid()} {time.time():.6f}\n".encode("utf-8")
                os.write(fd, payload)
            finally:
                os.close(fd)
            return
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for book reconcile lock: {path}")
            time.sleep(_BOOK_LOCK_POLL_SEC)


def _release_process_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


@contextmanager
def session_lane(session_id: str):
    lock = _session_locks[session_id]
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


@contextmanager
def book_lane():
    path = _book_lock_path()
    _book_thread_lock.acquire()
    depth = int(getattr(_book_thread_state, "depth", 0) or 0)
    outermost = depth == 0
    try:
        if outermost:
            _acquire_process_lock(path)
        _book_thread_state.depth = depth + 1
        yield
    finally:
        next_depth = max(int(getattr(_book_thread_state, "depth", 1) or 1) - 1, 0)
        _book_thread_state.depth = next_depth
        if outermost:
            _release_process_lock(path)
        _book_thread_lock.release()
