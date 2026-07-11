import pytest

from gp_assistant.book.readonly import build_daily_plan_artifact, tracked_universe_from_daybook
from gp_assistant.book.repo import compose_market_book
from gp_assistant.contracts.objects import AdvicePick, DayBook
from gp_assistant.runtime.current_v2 import _item, current_book_to_v2
from gp_assistant.runtime.producer import producer_metadata


@pytest.mark.parametrize(
    "phase",
    ["PREOPEN", "OPEN_NO_FIRST_BAR", "LUNCH_BREAK", "CLOSING_AUCTION", "POSTCLOSE_PENDING", "POSTCLOSE_READY", "NON_TRADING"],
)
def test_daily_plan_is_not_publishable_in_non_execution_phases(phase):
    daybook = DayBook(
        trading_day="20260710",
        generated_at="2026-07-10T16:00:00+08:00",
        tradeable=True,
        picks=[AdvicePick(symbol="600519", rank=1, entry_plan={"low": 1.0}, stop_plan={"price": 0.9})],
        producer=producer_metadata(),
    )
    artifact = build_daily_plan_artifact(
        daybook=daybook,
        tracked_universe=tracked_universe_from_daybook(daybook),
        market_phase=phase,
        trade_day="20260710",
        portfolio_snapshot={},
    )
    assert artifact.publish_allowed is False


def test_non_trading_current_v2_keeps_plan_but_disables_execution():
    daybook = DayBook(
        trading_day="20260710",
        generated_at="2026-07-10T16:00:00+08:00",
        tradeable=True,
        picks=[
            AdvicePick(
                symbol="600519",
                rank=1,
                thesis="daily plan",
                entry_plan={"low": 1400.0, "high": 1420.0},
                stop_plan={"price": 1370.0},
                take_profit_plan={"targets": [1500.0]},
                scores={"final": 0.72},
            )
        ],
        producer=producer_metadata(),
    )
    artifact = build_daily_plan_artifact(
        daybook=daybook,
        tracked_universe=tracked_universe_from_daybook(daybook),
        market_phase="NON_TRADING",
        trade_day="20260710",
        portfolio_snapshot={},
    )
    book = compose_market_book(daybook, artifact)
    book.producer = producer_metadata()

    payload = current_book_to_v2(book)

    assert payload["source"] == "current_book"
    assert payload["symbols"] == ["600519"]
    assert len(payload["items"]) == 1
    assert payload["tradeable"] is False
    assert payload["publish_allowed"] is False
    assert payload["non_trading"] is True
    assert payload["items"][0]["actionable"] is False
    assert 0.0 <= payload["items"][0]["final_score"] <= 1.0


def test_current_v2_preserves_explicit_zero_adaptive_values():
    daybook = DayBook(
        trading_day="20260710",
        generated_at="2026-07-10T16:00:00+08:00",
        tradeable=True,
        picks=[AdvicePick(symbol="600519", rank=1, entry_plan={"low": 1.0}, stop_plan={"price": 0.9})],
        producer=producer_metadata(),
    )
    artifact = build_daily_plan_artifact(
        daybook=daybook,
        tracked_universe=tracked_universe_from_daybook(daybook),
        market_phase="NON_TRADING",
        trade_day="20260710",
        portfolio_snapshot={},
    )
    entry = artifact.board[0]
    entry.pick.explain_context["adaptive_policy"] = {
        "calibrated_probability": 0.0,
        "confidence": 0.0,
        "feature_coverage": 0.0,
    }
    item = _item(entry, run_id="run", publish_allowed=False)
    assert item["calibrated_probability"] == 0.0
    assert item["confidence"] == 0.0
    assert item["reliability_score"] == 0.0
