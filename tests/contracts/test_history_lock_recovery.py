from __future__ import annotations

from time import time

from gp_assistant.search.history_store import _acquire_process_lock, _release_process_lock


def test_process_lock_reclaims_a_stale_container_lock(tmp_path):
    lock = tmp_path / ".history.lock"
    lock.write_text(f"1 {time() - 600:.6f} abandoned-token\n", encoding="utf-8")

    token = _acquire_process_lock(lock, timeout_sec=0.2, poll_sec=0.01, stale_after_sec=60)

    assert token in lock.read_text(encoding="utf-8")
    _release_process_lock(lock, token)
    assert not lock.exists()
