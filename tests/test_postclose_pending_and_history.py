from gp_assistant.contracts.objects import AdvicePick, BoardEntry, DayBook, EvidencePack, MarketBook, SessionState, TurnFrame
from gp_assistant.judgment.engine import make_judgment


def _mk_entry(sym: str, rank: int) -> BoardEntry:
    pick = AdvicePick(
        symbol=sym,
        rank=rank,
        thesis="计划保留",
        why_selected="主线强度仍在",
        entry_plan={"price": 10.2},
        stop_plan={"price": 9.8},
        take_profit_plan={"targets": [10.8]},
    )
    return BoardEntry(
        symbol=sym,
        name=None,
        rank=rank,
        final_score=1.0,
        live_score=1.0,
        execution_state="watch",
        can_open=False,
        stretched=False,
        invalidated=False,
        summary="x",
        style_label=None,
        pick=pick,
        pulse=None,
    )


def test_postclose_recommend_returns_next_session_plan():
    db = DayBook(trading_day="20240320", generated_at="2024-03-20T15:01:00", tradeable=True)
    book = MarketBook(trading_day="20240320", book_version="b1", updated_at="2024-03-20T15:01:00", regime={}, daybook=db)
    book.board = [_mk_entry("600519", 1), _mk_entry("000001", 2)]
    book.market_phase = "POSTCLOSE_PENDING"
    book.data_status = "close_pending"
    book.slot_status = "DEGRADED"
    book.publish_allowed = False
    session = SessionState(session_id="s", created_at="t", updated_at="t")
    frame = TurnFrame(frame_id="f", raw_message="收盘了也给我三只", subject="run", request="recommend", freshness="next_session_plan")
    ev = EvidencePack(frame=frame, session=session, book=book)
    j = make_judgment(session_id="s", frame=frame, evidence=ev)
    assert j.kind == "recommend"
    assert j.canonical_run is not None
    assert j.canonical_run.non_trading is True
    assert j.canonical_run.publish_allowed is False
    assert all(p.execution_state in {"WAIT_NEXT_SESSION", "WATCH_ONLY"} for p in j.canonical_run.picks)


def test_history_keyword_sets_need_previous_run():
    from gp_assistant.runtime.evidence_planner import plan_evidence

    frame = TurnFrame(frame_id="f", raw_message="为什么这次和上次不一样", subject="run", request="run_change", freshness="active_run")
    plan = plan_evidence(frame)
    assert plan["need_previous_run"] is True
