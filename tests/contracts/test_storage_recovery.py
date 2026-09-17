from __future__ import annotations

from datetime import datetime
import sqlite3
import subprocess
import sys
from threading import Thread
from zoneinfo import ZoneInfo

import pytest

from gp_assistant.search import history_store
from gp_assistant.application import market_orchestrator as module
from gp_assistant.application.market_runs import MarketRunStore
from gp_assistant.store import ContractStore
from tests.contracts.test_daily_refresh_exact_coverage import _frozen


def test_worker_recovers_real_interrupted_transaction_without_losing_committed_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path))
    path = history_store.history_db_path()
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE evidence(id INTEGER PRIMARY KEY, value TEXT)")
    conn.executemany("INSERT INTO evidence VALUES (?,?)", [(i, "original" * 500) for i in range(100)])
    conn.commit()
    conn.close()
    subprocess.run([sys.executable, "-c", """
import sqlite3,sys,os
c=sqlite3.connect(sys.argv[1])
c.execute('PRAGMA cache_size=5')
c.execute("UPDATE evidence SET value=replace(value,'original','modified')")
os._exit(0)
""", str(path)], check=True)
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError) as caught:
            conn.execute("SELECT count(*) FROM evidence").fetchone()
        assert caught.value.sqlite_errorcode == sqlite3.SQLITE_READONLY_ROLLBACK
    finally:
        conn.close()
    history_store.recover_history_database()
    history_store.recover_history_database()  # safe to repeat
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        assert conn.execute("SELECT count(*) FROM evidence WHERE value=?", ("original" * 500,)).fetchone()[0] == 100
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    finally:
        conn.close()


def test_lock_cleanup_does_not_mask_original_or_leak_thread_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path))
    monkeypatch.setattr(history_store, "_release_process_lock", lambda *_args: (_ for _ in ()).throw(OSError("mount unavailable")))
    with pytest.raises(sqlite3.OperationalError, match="commit failed") as caught:
        with history_store.history_db_lane():
            raise sqlite3.OperationalError("commit failed")
    assert "mount unavailable" in caught.value.__notes__[0]
    acquired = []
    def probe():
        ok = history_store._DB_LOCK.acquire(timeout=1)
        acquired.append(ok)
        if ok:
            history_store._DB_LOCK.release()
    thread = Thread(target=probe)
    thread.start()
    thread.join(timeout=2)
    assert acquired == [True]


def test_daily_storage_failure_is_recorded_and_lease_released(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path))
    ledger = MarketRunStore(tmp_path / "market_runs.db")
    now = datetime(2026, 7, 24, 16, tzinfo=ZoneInfo("Asia/Shanghai"))
    ledger.ensure_run(universe=_frozen(), now=now)
    monkeypatch.setattr(module, "recover_history_database", lambda: (_ for _ in ()).throw(sqlite3.OperationalError("disk I/O error")))
    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        module._daily_fetch_worker(run_db=str(ledger.path), trade_date="2026-07-24", now_iso=now.isoformat(), lease_sec=90)
    run = ledger.get_run("2026-07-24")
    assert run.state == "retry_wait" and "disk I/O" in run.last_error
    assert run.next_retry_at is not None
    assert ledger.acquire_lease(name="daily-run:2026-07-24", now=now, lease_sec=90) is not None


def test_parent_records_unhandled_child_exit(tmp_path):
    now = datetime(2026, 7, 24, 16, tzinfo=ZoneInfo("Asia/Shanghai"))
    ledger = MarketRunStore(tmp_path / "market_runs.db")
    ledger.ensure_run(universe=_frozen(), now=now)
    ledger.set_source_ready("2026-07-24", now)
    worker = module.MarketDayOrchestrator(ContractStore(tmp_path / "contracts.db"), ledger=ledger)
    class DeadProcess:
        exitcode = -9
        closed = False
        def is_alive(self): return False
        def join(self, timeout): pass
        def close(self): self.closed = True
    process = DeadProcess()
    worker._fetch_process = process
    worker._fetch_trade_date = "2026-07-24"
    worker._reap_fetch_process(now=now)
    run = ledger.get_run("2026-07-24")
    assert run.state == "retry_wait" and run.last_error == "daily_process_exit:-9"
    assert worker._fetch_process is None and process.closed


def test_refresh_io_failure_never_becomes_provider_exclusion(tmp_path, monkeypatch):
    ledger = MarketRunStore(tmp_path / "market_runs.db")
    now = datetime(2026, 7, 24, 16, tzinfo=ZoneInfo("Asia/Shanghai"))
    ledger.ensure_run(universe=_frozen(), now=now)
    monkeypatch.setattr(module, "recover_history_database", lambda: None)
    monkeypatch.setattr(module, "lifecycle_exclusions", lambda **kwargs: {})
    monkeypatch.setattr(module, "coverage_for_date", lambda *args, **kwargs: {})
    monkeypatch.setattr(module, "get_provider", lambda **kwargs: object())
    monkeypatch.setattr(module.DailyEvidenceRefresher, "refresh", lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("commit disk I/O")))
    with pytest.raises(sqlite3.OperationalError, match="commit disk I/O"):
        module._daily_fetch_worker(run_db=str(ledger.path), trade_date="2026-07-24", now_iso=now.isoformat(), lease_sec=90)
    run = ledger.get_run("2026-07-24")
    assert run.state == "retry_wait" and "commit disk I/O" in run.last_error
    assert not run.universe.excluded_symbols


def test_parent_preserves_recovery_error_when_ledger_also_fails(tmp_path, monkeypatch):
    ledger = MarketRunStore(tmp_path / "market_runs.db")
    worker = module.MarketDayOrchestrator(ContractStore(tmp_path / "contracts.db"), ledger=ledger)
    monkeypatch.setattr(module, "recover_history_database", lambda: (_ for _ in ()).throw(sqlite3.OperationalError("original recovery I/O")))
    monkeypatch.setattr(ledger, "health", lambda: (_ for _ in ()).throw(OSError("ledger unavailable")))
    with pytest.raises(sqlite3.OperationalError, match="original recovery I/O"):
        worker.tick(now=datetime(2026, 7, 24, 16, tzinfo=ZoneInfo("Asia/Shanghai")))

