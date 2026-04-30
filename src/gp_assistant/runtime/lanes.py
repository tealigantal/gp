from __future__ import annotations

import os
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock, RLock, Thread, local

from ..core.paths import store_dir


_session_locks: dict[str, Lock] = defaultdict(Lock)
_book_thread_lock = RLock()
_book_thread_state = local()
_BOOK_LOCK_TIMEOUT_SEC = 30.0
_BOOK_LOCK_POLL_SEC = 0.05
_BOOK_LOCK_STALE_SEC = float(os.getenv("GP_BOOK_LOCK_STALE_SEC", "20"))
_BOOK_LOCK_HEARTBEAT_SEC = 5.0


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
            if _is_stale_process_lock(path):
                _release_process_lock(path)
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for book reconcile lock: {path}")
            time.sleep(_BOOK_LOCK_POLL_SEC)


def _is_stale_process_lock(path: Path) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age >= max(1.0, _BOOK_LOCK_STALE_SEC)


def _start_lock_heartbeat(path: Path) -> Event:
    stop = Event()

    def _beat() -> None:
        while not stop.wait(_BOOK_LOCK_HEARTBEAT_SEC):
            try:
                os.utime(path, None)
            except FileNotFoundError:
                return

    Thread(target=_beat, name="gp-book-lock-heartbeat", daemon=True).start()
    return stop


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
    heartbeat_stop: Event | None = None
    try:
        if outermost:
            _acquire_process_lock(path)
            heartbeat_stop = _start_lock_heartbeat(path)
        _book_thread_state.depth = depth + 1
        yield
    finally:
        next_depth = max(int(getattr(_book_thread_state, "depth", 1) or 1) - 1, 0)
        _book_thread_state.depth = next_depth
        if outermost:
            if heartbeat_stop is not None:
                heartbeat_stop.set()
            _release_process_lock(path)
        _book_thread_lock.release()
