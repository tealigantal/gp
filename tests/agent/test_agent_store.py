from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from gp_assistant.agent_store import AgentStore, SnapshotIntegrityError
from gp_assistant.chat_agent import run_chat_turn
from gp_assistant.contracts.objects import AdvicePick, BoardEntry, DayBook, MarketBook


def make_book(snapshot_id: str = "snapshot-1") -> MarketBook:
    pick = AdvicePick(symbol="600519", name="贵州茅台", rank=1, thesis="强势延续", entry_plan={"price": 100}, stop_plan={"price": 90}, take_profit_plan={"price": 110}, why_selected="评分第一", risk_flags=["波动风险"], evidence_refs=["evidence:600519"])
    entry = BoardEntry(symbol="600519", name="贵州茅台", rank=1, final_score=0.9, live_score=0.8, execution_state="watch", can_open=True, stretched=False, invalidated=False, summary="趋势与流动性符合当前策略", pick=pick)
    return MarketBook(trading_day="20260713", book_version=snapshot_id, artifact_id=snapshot_id, updated_at="2026-07-13T10:00:00+08:00", regime={}, daybook=DayBook(trading_day="20260713", generated_at="2026-07-13T09:00:00+08:00", tradeable=True, picks=[pick]), board=[entry], publish_allowed=True)


def test_snapshot_is_immutable_and_pointer_is_valid(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    first = store.publish_book(make_book())
    assert store.current_snapshot().snapshot_id == first.snapshot_id
    altered = make_book()
    altered.daybook.picks[0].why_selected = "被篡改"
    with pytest.raises(SnapshotIntegrityError, match="immutable"):
        store.publish_book(altered)


def test_turn_commit_is_atomic_idempotent_and_integrity_checked(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())
    first = run_chat_turn(session_id="s1", client_turn_id="c1", user_message="推荐", store=store)
    retried = run_chat_turn(session_id="s1", client_turn_id="c1", user_message="推荐", store=store)
    assert retried == first
    assert [(turn["seq"], turn["role"]) for turn in store.session_turns("s1")] == [(1, "user"), (2, "assistant")]
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_concurrent_distinct_turns_have_no_duplicate_sequence(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda index: run_chat_turn(session_id="s1", client_turn_id=f"c{index}", user_message="推荐", store=store), range(4)))
    assert {result["client_turn_id"] for result in results} == {"c0", "c1", "c2", "c3"}
    assert [turn["seq"] for turn in store.session_turns("s1")] == list(range(1, 9))


def test_missing_snapshot_returns_structured_no_trade_without_legacy_read(tmp_path):
    result = run_chat_turn(session_id="new", client_turn_id="c1", user_message="推荐", store=AgentStore(tmp_path / "agent.db"))
    assert result["decision"] == "no_trade"
    assert result["snapshot_id"] is None
    assert result["message"]["reason"] == "current_snapshot_unavailable"


def test_follow_up_remains_bound_to_first_session_snapshot(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book("snapshot-1"))
    first = run_chat_turn(session_id="s1", client_turn_id="c1", user_message="推荐", store=store)
    store.publish_book(make_book("snapshot-2"))
    second = run_chat_turn(session_id="s1", client_turn_id="c2", user_message="600519 为什么", store=store)
    assert first["snapshot_id"] == second["snapshot_id"] == "snapshot-1"
