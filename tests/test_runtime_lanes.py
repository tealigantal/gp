from __future__ import annotations

import os
import time

from gp_assistant.runtime import lanes
from gp_assistant.runtime.lanes import _book_lock_path, book_lane


def test_book_lane_is_reentrant_and_cleans_lockfile():
    lock_path = _book_lock_path()
    if lock_path.exists():
        lock_path.unlink()

    with book_lane():
        assert lock_path.exists()
        with book_lane():
            assert lock_path.exists()

    assert not lock_path.exists()


def test_book_lane_cleans_stale_lockfile(monkeypatch):
    lock_path = _book_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("stale 0\n", encoding="utf-8")
    old = time.time() - 5
    os.utime(lock_path, (old, old))
    monkeypatch.setattr(lanes, "_BOOK_LOCK_STALE_SEC", 1.0)

    with book_lane():
        assert lock_path.exists()

    assert not lock_path.exists()
