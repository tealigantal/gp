from __future__ import annotations

import pandas as pd

from gp_assistant.book.pulse5m import evaluate_slot_pulses, score_intraday_gate
from gp_assistant.contracts.objects import AdvicePick, AdviceRun, BoardEntry, DayBook, EvidencePack, MarketBook, SessionState, SlotGate, TrackedUniverse, TurnFrame
from gp_assistant.evidence.market_service import build_slot_breadth_snapshot
from gp_assistant.judgment.engine import make_judgment


def _bars(close_values, *, vols):
    times = pd.date_range("2024-03-20 09:35:00", periods=len(close_values), freq="5min")
    rows = []
    prev = 10.0
    for idx, close in enumerate(close_values):
        open_px = prev
        rows.append(
            {
                "trade_time": times[idx],
                "open": open_px,
                "high": max(open_px, close) + 0.03,
                "low": min(open_px, close) - 0.02,
                "close": close,
                "vol": vols[idx],
                "amount": close * vols[idx],
            }
        )
        prev = close
    return pd.DataFrame(rows)


def _pick(symbol: str, rank: int) -> AdvicePick:
    return AdvicePick(
        symbol=symbol,
        rank=rank,
        thesis=f"{symbol} thesis",
        why_selected=f"{symbol} why",
        entry_plan={"high": 10.30, "mid": 10.18},
        stop_plan={"price": 9.85},
        take_profit_plan={"targets": [10.80]},
    )


def _entry(symbol: str, rank: int) -> BoardEntry:
    return BoardEntry(
        symbol=symbol,
        name=symbol,
        rank=rank,
        final_score=0.9,
        live_score=0.8,
        execution_state="watch",
        can_open=False,
        stretched=False,
        invalidated=False,
        summary="summary",
        pick=_pick(symbol, rank),
    )


def _stale_entry(symbol: str, rank: int, *, freshness_state: str = "failed_refresh", last_date: str = "2024-03-19") -> BoardEntry:
    pick = _pick(symbol, rank)
    pick.meta["daily_freshness_state"] = freshness_state
    pick.meta["daily_last_date"] = last_date
    return BoardEntry(
        symbol=symbol,
        name=symbol,
        rank=rank,
        final_score=0.9,
        live_score=0.8,
        execution_state="watch",
        can_open=False,
        stretched=False,
        invalidated=False,
        summary="summary",
        pick=pick,
    )


def test_derived_snapshot_keeps_gate_available():
    daybook = DayBook(trading_day="20240320", generated_at="2024-03-20T09:00:00+08:00", picks=[_pick("600519", 1), _pick("000001", 2)])
    tracked = TrackedUniverse(reco=["600519", "000001"], reserve=[], portfolio=[], total=["600519", "000001"])
    symbol_bars = {
        "600519": _bars([10.00, 10.05, 10.08, 10.10, 10.12, 10.15, 10.25], vols=[90, 95, 100, 105, 110, 100, 150]),
        "000001": _bars([10.00, 10.04, 10.07, 10.09, 10.12, 10.14, 10.22], vols=[88, 92, 98, 103, 108, 102, 148]),
    }
    benchmark = _bars([10.00, 10.01, 10.01, 10.02, 10.02, 10.03, 10.03], vols=[100, 100, 100, 100, 100, 100, 100])
    snapshot = build_slot_breadth_snapshot(symbol_bars, slot_at="2024-03-20 10:05:00")
    provisional_pulses = evaluate_slot_pulses(
        daybook=daybook,
        tracked_universe=tracked,
        bars=symbol_bars,
        benchmark=benchmark,
        slot_baselines={"600519": {"10:05": 100.0}, "000001": {"10:05": 100.0}},
        gate=SlotGate(state="ALLOW", score=80.0, reasons=["ok"]),
        slot_at="2024-03-20 10:05:00",
        trade_day="20240320",
        provider="akshare",
    )
    gate = score_intraday_gate(
        snapshot=snapshot,
        benchmark=benchmark,
        pulses=provisional_pulses,
        tracked_universe=tracked,
        data_complete=True,
    )
    assert gate.state in {"ALLOW", "DEGRADED", "BLOCKED"}
    assert "up_ratio" in gate.metrics


def test_live_entry_states_cover_buy_wait_risk_invalidated():
    daybook = DayBook(
        trading_day="20240320",
        generated_at="2024-03-20T09:00:00+08:00",
        picks=[_pick("BUY", 1), _pick("WAIT", 2), _pick("RISK", 3), _pick("INV", 4)],
    )
    tracked = TrackedUniverse(reco=["BUY", "WAIT", "RISK", "INV"], reserve=[], portfolio=[], total=["BUY", "WAIT", "RISK", "INV"])
    bars = {
        "BUY": _bars([10.00, 10.05, 10.08, 10.10, 10.12, 10.15, 10.25], vols=[90, 95, 100, 105, 110, 100, 150]),
        "WAIT": _bars([10.00, 10.02, 10.06, 10.09, 10.12, 10.13, 10.17], vols=[90, 92, 95, 100, 102, 103, 98]),
        "RISK": _bars([10.00, 10.04, 10.09, 10.16, 10.25, 10.34, 10.47], vols=[90, 95, 100, 110, 120, 130, 160]),
        "INV": _bars([10.00, 9.98, 9.95, 9.92, 9.90, 9.88, 9.80], vols=[90, 95, 100, 105, 110, 100, 150]),
    }
    benchmark = _bars([10.00, 10.01, 10.01, 10.02, 10.02, 10.03, 10.03], vols=[100, 100, 100, 100, 100, 100, 100])
    pulses = evaluate_slot_pulses(
        daybook=daybook,
        tracked_universe=tracked,
        bars=bars,
        benchmark=benchmark,
        slot_baselines={symbol: {"10:05": 100.0} for symbol in tracked.total},
        gate=SlotGate(state="ALLOW", score=80.0, reasons=["ok"]),
        slot_at="2024-03-20 10:05:00",
        trade_day="20240320",
        provider="akshare",
    )
    assert pulses["BUY"].action == "BUY"
    assert pulses["WAIT"].execution_state in {"wait_pullback", "observe"}
    assert pulses["RISK"].execution_state in {"extended", "breakout_buy"}
    assert pulses["INV"].execution_state == "invalidated"


def test_pick_detail_active_run_uses_current_run():
    entry = _entry("600519", 1)
    book = MarketBook(
        trading_day="20240320",
        book_version="book1",
        updated_at="2024-03-20T10:00:00+08:00",
        regime={},
        daybook=DayBook(trading_day="20240320", generated_at="2024-03-20T09:00:00+08:00", tradeable=True),
        board=[entry],
        watchset=[],
        symbol_states={},
        portfolio_snapshot={},
        last_closed_5m="2024-03-20 10:00:00",
        side_results=[],
        market_phase="INTRADAY_PM",
        slot_status="OK",
        publish_allowed=True,
    )
    frame = TurnFrame(frame_id="f", raw_message="第二只为什么", subject="pick", request="pick_detail", freshness="active_run", references={"symbol": "600519"})
    run = AdviceRun(run_id="run1", session_id="s1", book_version="book1", created_at="t", trading_day="20240320", picks=[entry])
    ev = EvidencePack(frame=frame, session=SessionState(session_id="s1", created_at="t", updated_at="t"), book=book, active_run=run, subject_entry=entry)
    judgment = make_judgment("s1", frame, ev)
    assert judgment.kind == "pick_detail"
    assert judgment.pick_detail is not None
    assert judgment.pick_detail.symbol == "600519"


def test_exit_decision_returns_structured_action():
    entry = _entry("600519", 1)
    book = MarketBook(
        trading_day="20240320",
        book_version="book1",
        updated_at="2024-03-20T10:00:00+08:00",
        regime={},
        daybook=DayBook(trading_day="20240320", generated_at="2024-03-20T09:00:00+08:00", tradeable=True),
        board=[entry],
        watchset=[],
        symbol_states={},
        portfolio_snapshot={},
        last_closed_5m="2024-03-20 10:00:00",
        side_results=[],
        market_phase="INTRADAY_PM",
        slot_status="OK",
        publish_allowed=True,
    )
    frame = TurnFrame(frame_id="f", raw_message="600519 现在该不该卖", subject="holding", request="exit_decision", freshness="active_run", references={"symbol": "600519"})
    ev = EvidencePack(frame=frame, session=SessionState(session_id="s1", created_at="t", updated_at="t"), book=book, subject_entry=entry)
    judgment = make_judgment("s1", frame, ev)
    assert judgment.kind == "exit_decision"
    assert judgment.exit_decision is not None
    assert judgment.exit_decision.action in {"HOLD", "REDUCE", "SELL", "WATCH"}


def test_stale_daily_symbol_blocks_formal_pick_decisions():
    entry = _stale_entry("600519", 1)
    daybook = DayBook(
        trading_day="20240320",
        generated_at="2024-03-20T09:00:00+08:00",
        tradeable=False,
        reason="daily_freshness_blocked",
        picks=[entry.pick],
        source_meta={
            "daily_freshness": {
                "ready": False,
                "target_day": "2024-03-20",
                "stale_symbols": ["600519"],
                "failed_symbols": ["600519"],
                "blocking_reason": "日线数据未补齐到目标交易日 2024-03-20：600519",
            }
        },
    )
    book = MarketBook(
        trading_day="20240320",
        book_version="book1",
        updated_at="2024-03-20T10:00:00+08:00",
        regime={},
        daybook=daybook,
        board=[entry],
        watchset=[],
        symbol_states={},
        portfolio_snapshot={},
        last_closed_5m="2024-03-20 10:00:00",
        side_results=[],
        market_phase="INTRADAY_PM",
        slot_status="OK",
        publish_allowed=True,
    )
    frame = TurnFrame(frame_id="f", raw_message="这只现在还能买吗", subject="symbol", request="live_entry_check", freshness="active_run", references={"symbol": "600519"})
    run = AdviceRun(run_id="run1", session_id="s1", book_version="book1", created_at="t", trading_day="20240320", picks=[entry])
    ev = EvidencePack(frame=frame, session=SessionState(session_id="s1", created_at="t", updated_at="t"), book=book, active_run=run, subject_entry=entry)

    judgment = make_judgment("s1", frame, ev)

    assert judgment.kind == "live_entry_check"
    assert judgment.live_entry is not None
    assert judgment.live_entry.execution_state == "UNAVAILABLE"
    assert "日线未补齐" in judgment.live_entry.summary
