from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from gp_assistant.agent_store import (
    AgentStore,
    SessionSnapshotConflict,
    StorageBusyError,
    _migration_checksum,
)
from gp_assistant.chat_agent import run_chat_turn
from gp_assistant.evidence import daily_freshness
from gp_assistant.gateway.app import app
from gp_assistant.gateway import routes
from gp_assistant.market_memory.store import make_market_event, upsert_market_event
from gp_assistant.runtime.market_clock import PHASE_PREOPEN
from gp_assistant.runtime.market_time import MarketTimeContext
from tests.agent.test_agent_store import make_book, patch_chat_llm
from fastapi.testclient import TestClient


def test_monday_preopen_separates_planned_and_completed_days(monkeypatch):
    state = type("State", (), {
        "market_phase": PHASE_PREOPEN,
        "target_daybook_effective_day": "20260713",
        "target_pulse_trade_day": "20260713",
        "target_pulse_slot_at": None,
        "calendar_status": "ok", "calendar_source": "test", "calendar_range_start": None,
        "calendar_range_end": None, "next_trading_day": "20260713", "calendar_error": None,
    })()
    monkeypatch.setattr(daily_freshness, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(daily_freshness, "_previous_open_day_ymd", lambda _: "20260710")

    context = daily_freshness.resolve_daily_target(now="ignored")

    assert context.decision_trade_day == "2026-07-13"
    assert context.daybook_effective_day == "2026-07-10"
    assert context.daybook_effective_day == "2026-07-10"


def test_readers_do_not_wait_for_a_writer_transaction(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())
    writer = sqlite3.connect(store.path, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda _: store.health_snapshot()["current_snapshot_id"], range(100)))
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    assert set(results) == {"snapshot-1"}
    assert time.monotonic() - started < 0.5


def test_health_waits_for_short_exclusive_commit_and_reads_real_current(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())
    writer = sqlite3.connect(
        store.path, isolation_level=None, check_same_thread=False
    )
    writer.execute("BEGIN EXCLUSIVE")

    def release_writer():
        time.sleep(0.7)
        writer.execute("ROLLBACK")
        writer.close()

    release = threading.Thread(target=release_writer)
    release.start()
    started = time.monotonic()
    health = store.health_snapshot()
    elapsed = time.monotonic() - started
    release.join(timeout=2)

    assert health["current_snapshot_id"] == "snapshot-1"
    assert 0.5 <= elapsed < 2.0


def test_health_decodes_snapshot_after_releasing_read_transaction(
    tmp_path, monkeypatch
):
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book("snapshot-1"))
    decode_started = threading.Event()
    release_decode = threading.Event()
    original_decode = store._decode_snapshot

    def blocked_decode(row):
        decode_started.set()
        assert release_decode.wait(timeout=2)
        return original_decode(row)

    monkeypatch.setattr(store, "_decode_snapshot", blocked_decode)
    with ThreadPoolExecutor(max_workers=1) as pool:
        health_future = pool.submit(store.health_snapshot)
        assert decode_started.wait(timeout=2)
        started = time.monotonic()
        store.publish_book(make_book("snapshot-2"))
        assert time.monotonic() - started < 1.0
        release_decode.set()
        health = health_future.result(timeout=2)

    assert health["current_snapshot_id"] == "snapshot-1"
    assert store.current_snapshot().snapshot_id == "snapshot-2"


def test_first_session_snapshot_binding_cannot_be_overwritten(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book("snapshot-a"))
    store.publish_book(make_book("snapshot-b"))

    def commit(snapshot_id: str):
        return store.commit_turn(
            session_id="race", client_turn_id=snapshot_id, user_content="为什么", assistant_content="ok",
            assistant_payload={"snapshot_id": snapshot_id}, snapshot_id=snapshot_id, claims=[],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(commit, snapshot_id) for snapshot_id in ("snapshot-a", "snapshot-b")]
        outcomes = [future.exception() for future in futures]
    assert sum(isinstance(outcome, SessionSnapshotConflict) for outcome in outcomes) == 1
    bound = store.session_snapshot("race")
    assert bound is not None
    assert bound.snapshot_id in {"snapshot-a", "snapshot-b"}


def test_cross_day_explanation_is_historical_but_execution_is_no_trade(tmp_path, monkeypatch):
    patch_chat_llm(monkeypatch)
    store = AgentStore(tmp_path / "agent.db")
    old = make_book(
        "old",
        decision_trade_day="2026-07-13",
        daybook_effective_day="2026-07-10",
    )
    store.publish_book(old)
    run_chat_turn(session_id="s", client_turn_id="one", user_message="为什么入选", store=store)
    new = make_book(
        "new",
        decision_trade_day="2026-07-14",
        daybook_effective_day="2026-07-13",
    )
    store.publish_book(new)

    historical = run_chat_turn(session_id="s", client_turn_id="two", user_message="为什么入选", store=store)
    blocked = run_chat_turn(session_id="s", client_turn_id="three", user_message="当前推荐", store=store)

    assert historical["message"]["perspective"] == "historical"
    assert historical["message"]["is_current"] is False
    assert blocked["decision"] == "no_trade"
    assert blocked["message"]["decision_reason"] == "historical_snapshot_not_tradeable"


def test_market_memory_rejects_unmatured_or_invalid_complete_event(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))
    event = make_market_event(
        as_of="2026-07-10", symbol="600000", signal_type="test", feature_vector={"trend_strength": 1.0},
        features={}, market_context={}, outcome={"complete": True, "outcome_available_trading_day": "2026-07-10"}, data_provenance={},
    )
    with pytest.raises(ValueError, match="date_contract"):
        upsert_market_event(event)


def test_migration_checksum_and_busy_http_are_structured(tmp_path, monkeypatch):
    db = tmp_path / "bad.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, checksum TEXT NOT NULL)")
        conn.execute("INSERT INTO schema_migrations VALUES(1,'2026-07-13T00:00:00+08:00','bad')")
    with pytest.raises(Exception, match="agent_db_schema_mismatch"):
        AgentStore(db).initialize()

    monkeypatch.setattr(routes, "run_chat_turn", lambda **_: (_ for _ in ()).throw(StorageBusyError(321)))
    response = TestClient(app).post("/api/chat", json={"client_turn_id": "busy", "message": "推荐"})
    assert response.status_code == 503
    assert response.json()["error"]["detail"]["retry_after_ms"] == 321

    monkeypatch.setattr(
        routes.AgentStore,
        "health_snapshot",
        lambda _self: (_ for _ in ()).throw(StorageBusyError(654)),
    )
    health_response = TestClient(app).get("/api/health")
    assert health_response.status_code == 503
    assert health_response.json()["error"]["detail"]["retry_after_ms"] == 654


def test_calendar_blocking_reason_round_trips_with_snapshot(tmp_path):
    store = AgentStore(tmp_path / "calendar.db")
    market_time = MarketTimeContext(
        decision_trade_day="2026-07-13",
        daybook_effective_day="2026-07-13",
        pulse_trade_day=None,
        pulse_slot_closed_at=None,
        observed_at="2026-07-13T10:00:00+08:00",
        market_phase="non_trading",
        target_mode="previous_completed",
        calendar_blocking_reason="calendar_source_unavailable",
    )
    store.publish_book(make_book("calendar-snapshot"), market_time=market_time)

    assert (
        store.current_snapshot().calendar_blocking_reason
        == "calendar_source_unavailable"
    )


def test_agent_schema_v2_migrates_additively_to_v3(tmp_path):
    db = tmp_path / "v2.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE schema_migrations("
            "version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL,checksum TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO schema_migrations VALUES(1,'old',?)",
            (_migration_checksum(1),),
        )
        conn.execute(
            "INSERT INTO schema_migrations VALUES(2,'old',?)",
            (_migration_checksum(2),),
        )
        conn.execute(
            """
            CREATE TABLE recommendation_snapshots(
                snapshot_id TEXT PRIMARY KEY,schema_version TEXT NOT NULL,
                as_of TEXT NOT NULL,decision TEXT NOT NULL,tradeable INTEGER NOT NULL,
                payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,decision_trade_day TEXT,
                daybook_effective_day TEXT,pulse_trade_day TEXT,
                pulse_slot_closed_at TEXT,observed_at TEXT,market_phase TEXT,
                target_mode TEXT,pending_eod_day TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO recommendation_snapshots("
            "snapshot_id,schema_version,as_of,decision,tradeable,payload_json,"
            "payload_hash,created_at) VALUES('sentinel','RecommendationSnapshot.v1',"
            "'old','no_trade',0,'{}','sentinel-hash','old')"
        )
        conn.commit()

    AgentStore(db).initialize()
    with sqlite3.connect(db) as conn:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(recommendation_snapshots)"
            ).fetchall()
        }
        assert "calendar_blocking_reason" in columns
        assert conn.execute(
            "SELECT COUNT(*) FROM recommendation_snapshots WHERE snapshot_id='sentinel'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT checksum FROM schema_migrations WHERE version=3"
        ).fetchone()[0] == _migration_checksum(3)
