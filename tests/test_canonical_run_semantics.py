from __future__ import annotations

from gp_assistant.contracts.objects import AdvicePick, AdviceRun, BoardEntry, DayBook, MarketBook, SlotDataQuality, SlotGate
from gp_assistant.runtime.canonical_artifact import build_canonical_run


def _entry(symbol: str) -> BoardEntry:
    return BoardEntry(
        symbol=symbol,
        name=symbol,
        rank=1,
        final_score=1.0,
        live_score=1.0,
        execution_state="observe",
        can_open=False,
        stretched=False,
        invalidated=False,
        summary="summary",
        pick=AdvicePick(symbol=symbol, rank=1, thesis="t", why_selected="w"),
    )


def test_blocked_gate_with_all_watch_only_picks_is_not_recommend():
    entry = _entry("600111")
    book = MarketBook(
        trading_day="20260429",
        book_version="book1",
        updated_at="t",
        regime={},
        daybook=DayBook(trading_day="20260428", generated_at="t", tradeable=True, picks=[entry.pick]),
        board=[entry],
        watchset=[],
        symbol_states={},
        portfolio_snapshot={},
        side_results=[],
        artifact_id="artifact1",
        slot_status="OK",
        publish_allowed=False,
        daybook_effective_day="20260428",
        pulse_trade_day="20260429",
        pulse_slot_at="2026-04-29 14:10:00",
        market_phase="INTRADAY_PM",
        gate=SlotGate(state="BLOCKED", reasons=["buyable_count=0"]),
        data_quality=SlotDataQuality(provider="akshare", complete=True),
    )
    run = AdviceRun(run_id="run1", session_id="s1", book_version="book1", created_at="t", trading_day="20260429", picks=[entry])

    canonical = build_canonical_run(book=book, run=run, picks=run.picks)

    assert canonical.run_action != "RECOMMEND"
    assert canonical.run_action == "NO_TRADE"
