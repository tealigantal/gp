from __future__ import annotations

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
