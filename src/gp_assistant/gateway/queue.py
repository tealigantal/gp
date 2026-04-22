from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from threading import Lock


_session_locks: dict[str, Lock] = defaultdict(Lock)
_book_lock = Lock()


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
    _book_lock.acquire()
    try:
        yield
    finally:
        _book_lock.release()
