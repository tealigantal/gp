from __future__ import annotations

import pandas as pd

from gp_assistant.contracts.objects import (
    DayBook,
    EvidencePack,
    Judgment,
    MarketBook,
    ReplyBundle,
    SessionState,
    SingleStockAnalysisArtifact,
    TurnFrame,
)
from gp_assistant.evidence import single_stock_service
from gp_assistant.memory import service as memory_service
from gp_assistant.runtime import turn_loop
from gp_assistant.runtime.narrator import build_reply
from gp_assistant.runtime.utils import now_iso


def _daily(rows: int = 130) -> pd.DataFrame:
    dates = pd.date_range("2025-08-01", periods=rows, freq="B")
    close = pd.Series([10.0 + i * 0.02 for i in range(rows)])
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.03,
            "high": close + 0.08,
            "low": close - 0.08,
            "close": close,
            "volume": [1000000 + i * 100 for i in range(rows)],
            "amount": close * 1000000,
        }
    )


def _book() -> MarketBook:
    return MarketBook(
        trading_day="20260101",
        book_version="book_1",
        updated_at=now_iso(),
        regime={"grade": "B"},
        daybook=DayBook(trading_day="20260101", generated_at=now_iso(), regime={}),
        board=[],
        watchset=[],
        symbol_states={},
        portfolio_snapshot={},
        side_results=[],
        market_phase="INTRADAY_PM",
    )


def test_single_stock_service_builds_champion_artifact(monkeypatch):
    class DummyHub:
        def daily_ohlcv(self, symbol, as_of=None, min_len=120, prefer_cache_only=False):
            return _daily(), {"freshness_state": "current", "source": "test", "insufficient_history": False}

    monkeypatch.setattr(single_stock_service, "MarketDataHub", lambda: DummyHub())
    monkeypatch.setattr(single_stock_service, "target_day_iso", lambda: "2026-01-01")
    monkeypatch.setattr(
        single_stock_service,
        "build_single_stock_strategy_view",
        lambda symbol, daily, env_grade="C": {
            "champion": {"strategy": "S1", "score": 0.8, "freshness_state": "fresh"},
            "trade_plan": {"diagnostics": {"execution_state": "actionable", "reward_risk": 1.2}},
        },
    )

    artifact = single_stock_service.analyze_single_stock("600519", book=_book())

    assert artifact.symbol == "600519"
    assert artifact.overall_state == "PLAN_READY"
    assert artifact.champion["strategy"] == "S1"
    assert artifact.kline_summary["bars"] == 130


def test_single_stock_service_blocks_insufficient_history(monkeypatch):
    class DummyHub:
        def daily_ohlcv(self, symbol, as_of=None, min_len=120, prefer_cache_only=False):
            return _daily(30), {"freshness_state": "current", "source": "test", "insufficient_history": True}

    monkeypatch.setattr(single_stock_service, "MarketDataHub", lambda: DummyHub())
    monkeypatch.setattr(single_stock_service, "target_day_iso", lambda: "2026-01-01")

    artifact = single_stock_service.analyze_single_stock("600519", book=_book())

    assert artifact.overall_state == "UNAVAILABLE"
    assert "insufficient_history" in artifact.reason_codes
    assert artifact.champion == {}


def test_single_stock_service_blocks_stale_strategy_conclusion(monkeypatch):
    class DummyHub:
        def daily_ohlcv(self, symbol, as_of=None, min_len=120, prefer_cache_only=False):
            return _daily(), {"freshness_state": "stale", "source": "test", "insufficient_history": False}

    def fail_strategy(*args, **kwargs):
        raise AssertionError("stale daily data must not reach strategy analysis")

    monkeypatch.setattr(single_stock_service, "MarketDataHub", lambda: DummyHub())
    monkeypatch.setattr(single_stock_service, "target_day_iso", lambda: "2026-01-01")
    monkeypatch.setattr(single_stock_service, "build_single_stock_strategy_view", fail_strategy)

    artifact = single_stock_service.analyze_single_stock("600519", book=_book())

    assert artifact.overall_state == "STALE_OBSERVE"
    assert "daily_stale" in artifact.reason_codes
    assert artifact.champion == {}
    assert artifact.trade_plan == {}
    assert artifact.data_status["analysis_ready"] is False


def test_single_stock_reply_and_grounding(monkeypatch):
    monkeypatch.setattr(
        "gp_assistant.runtime.narrator.render_reply",
        lambda payload: (_ for _ in ()).throw(RuntimeError("LLM unavailable")),
    )
    artifact = SingleStockAnalysisArtifact(
        symbol="600519",
        as_of="2026-01-01",
        last_date="2026-01-01",
        data_status={"ok": True},
        kline_summary={"last_close": 100.0, "return_5d_pct": 2.5, "bars": 130},
        champion={"strategy": "S1", "score": 0.8, "freshness_state": "fresh"},
        trade_plan={"diagnostics": {"execution_state": "actionable", "reward_risk": 1.2}},
        overall_state="PLAN_READY",
    )
    frame = TurnFrame(
        frame_id="f1",
        raw_message="600519 怎么样",
        subject="symbol",
        request="single_stock_query",
        freshness="active_run",
        references={"symbol": "600519"},
    )
    evidence = EvidencePack(frame=frame, session=SessionState(session_id="s1", created_at="t", updated_at="t"), book=_book())
    judgment = Judgment(kind="single_stock_query", summary="ok", single_stock_analysis=artifact)

    reply = build_reply(session_id="s1", frame=frame, evidence=evidence, judgment=judgment)

    assert reply.kind == "single_stock_query"
    assert reply.symbols == ["600519"]
    assert reply.message["message_kind"] == "single_stock_query"
    assert "冠军策略" in reply.text


def test_commit_turn_single_stock_updates_focus_without_active_run(monkeypatch):
    session = SessionState(session_id="s1", created_at="t", updated_at="t", active_run_id="run_old")
    saved = {}

    monkeypatch.setattr(memory_service, "load_session", lambda session_id: session)
    monkeypatch.setattr(memory_service, "append_event", lambda event: None)
    monkeypatch.setattr(memory_service, "next_seq", lambda session_id: 1)
    monkeypatch.setattr(memory_service, "save_claims", lambda claims: None)
    monkeypatch.setattr(memory_service, "save_preferences", lambda session_id, prefs: None)
    monkeypatch.setattr(memory_service, "save_session", lambda updated: saved.setdefault("session", updated))

    artifact = SingleStockAnalysisArtifact(symbol="600519", overall_state="PLAN_READY")
    reply = ReplyBundle(
        session_id="s1",
        text="ok",
        kind="single_stock_query",
        symbols=["600519"],
        message={"message_kind": "single_stock_query", "narrative_text": "ok"},
    )
    judgment = Judgment(kind="single_stock_query", summary="ok", single_stock_analysis=artifact)

    updated = memory_service.commit_turn("s1", "600519 怎么样", reply, judgment)

    assert updated.active_run_id == "run_old"
    assert updated.last_focus_symbol == "600519"
    assert updated.focus_subject == {"type": "symbol", "symbol": "600519"}


def test_single_stock_query_does_not_require_runtime_market_ready():
    frame = TurnFrame(
        frame_id="f1",
        raw_message="600519 怎么样",
        subject="symbol",
        request="single_stock_query",
        freshness="active_run",
        references={"symbol": "600519"},
    )
    assert turn_loop._is_market_request(frame) is True
    assert turn_loop._requires_runtime_market_ready(frame) is False
