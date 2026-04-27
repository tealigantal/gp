from __future__ import annotations

from gp_assistant.contracts.objects import AdvicePick, AdviceRun, BoardEntry, DayBook, EvidencePack, MarketBook, SessionState, TurnFrame
from gp_assistant.judgment.engine import make_judgment
from gp_assistant.runtime.utils import now_iso


def _entry(symbol: str = "600519", rank: int = 1) -> BoardEntry:
    pick = AdvicePick(
        symbol=symbol,
        name="示例",
        rank=rank,
        strategy_id="s01",
        thesis="示例 thesis",
        why_selected="示例原因",
        entry_plan={"price": 10.0},
        stop_plan={"price": 9.6},
        take_profit_plan={"targets": [10.8]},
    )
    return BoardEntry(
        symbol=symbol,
        name="示例",
        rank=rank,
        final_score=1.0,
        live_score=1.0,
        execution_state="watch",
        can_open=False,
        stretched=False,
        invalidated=False,
        summary="摘要",
        style_label=None,
        pick=pick,
        pulse=None,
    )


def _book() -> MarketBook:
    db = DayBook(trading_day="20260101", generated_at=now_iso(), tradeable=True)
    return MarketBook(
        trading_day="20260101",
        book_version="v1",
        updated_at=now_iso(),
        daybook=db,
        board=[_entry()],
        watchset=[],
        symbol_states={},
        portfolio_snapshot={},
        last_closed_5m=None,
        side_results=[],
        market_phase="INTRADAY_PM",
        slot_status="OK",
        publish_allowed=True,
    )


def _session() -> SessionState:
    return SessionState(session_id="s1", created_at=now_iso(), updated_at=now_iso())


def test_pick_detail_market_no_subject_raises():
    frame = TurnFrame(
        frame_id="f1",
        raw_message="这只为什么",
        subject="market",
        request="pick_detail",
        freshness="active_run",
        references={},
        constraints={},
        ambiguity={"confidence": 0.9, "notes": []},
    )
    ev = EvidencePack(frame=frame, session=_session(), book=_book())
    try:
        make_judgment("s1", frame, ev)
        assert False, "should raise"
    except ValueError:
        assert True


def test_live_entry_check_with_subject_entry():
    frame = TurnFrame(
        frame_id="f2",
        raw_message="第二只现在还能买吗",
        subject="symbol",
        request="live_entry_check",
        freshness="latest_5m",
        references={"symbol": "600519"},
        constraints={},
        ambiguity={"confidence": 0.8, "notes": []},
    )
    ev = EvidencePack(frame=frame, session=_session(), book=_book(), subject_entry=_entry("600519", 1))
    j = make_judgment("s1", frame, ev)
    assert j.kind == "live_entry_check"
    assert j.live_entry is not None


def test_run_change_uses_runs_not_subject():
    frame = TurnFrame(
        frame_id="f3",
        raw_message="为什么这次和上次不一样",
        subject="run",
        request="run_change",
        freshness="active_run",
        references={},
        constraints={},
        ambiguity={"confidence": 0.7, "notes": []},
    )
    run_now = AdviceRun(run_id="r1", session_id="s1", book_version="v1", created_at=now_iso(), trading_day="20260101", picks=[_entry("000001", 1)])
    run_prev = AdviceRun(run_id="r0", session_id="s1", book_version="v0", created_at=now_iso(), trading_day="20251231", picks=[_entry("000002", 1)])
    ev = EvidencePack(frame=frame, session=_session(), book=_book(), active_run=run_now, previous_run=run_prev)
    j = make_judgment("s1", frame, ev)
    assert j.kind == "run_change"
    assert j.run_change_view is not None
