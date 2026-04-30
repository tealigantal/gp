from datetime import datetime
from types import SimpleNamespace

from gp_assistant.contracts.objects import DayBook, MarketBook, SessionState
from gp_assistant.runtime import freshness_policy
from gp_assistant.runtime.freshness_policy import make_refresh_plan
from gp_assistant.runtime.market_clock import (
    PHASE_NON_TRADING,
    PHASE_OPEN_NO_FIRST_BAR,
    PHASE_POSTCLOSE_PENDING,
    PHASE_PREOPEN,
    compute_market_state,
)


def _mk_session() -> SessionState:
    now = datetime(2024, 3, 20, 10, 0)
    return SessionState(session_id="s", created_at=str(now), updated_at=str(now))


def _mk_book(day: str = "20240319") -> MarketBook:
    db = DayBook(trading_day=day, generated_at="2024-03-19T16:10:00", regime={}, tradeable=False)
    return MarketBook(trading_day=day, book_version="v1", updated_at="2024-03-19T16:10:00", regime={}, daybook=db)


def test_preopen_targets_today_daybook():
    ms = compute_market_state(datetime(2024, 3, 20, 9, 20))
    assert ms.market_phase == PHASE_PREOPEN
    assert ms.target_daybook_effective_day == "20240320"


def test_open_no_first_bar_has_no_closed_slot():
    ms = compute_market_state(datetime(2024, 3, 20, 9, 32))
    assert ms.market_phase == PHASE_OPEN_NO_FIRST_BAR
    assert ms.target_pulse_trade_day == "20240320"
    assert ms.target_pulse_slot_at is None


def test_intraday_plan_keeps_today_daybook_and_slot():
    sess = _mk_session()
    plan = make_refresh_plan(session=sess, book=_mk_book("20240319"), user_message="现在还能买吗", now=datetime(2024, 3, 20, 10, 0))
    assert plan.level == "L1"
    assert plan.target_daybook_effective_day == "20240320"
    assert plan.target_pulse_trade_day == "20240320"


def test_intraday_plan_downgrades_when_runtime_disabled(monkeypatch):
    monkeypatch.setattr(freshness_policy, "load_config", lambda: SimpleNamespace(intraday_runtime_enabled=False))
    sess = _mk_session()
    plan = make_refresh_plan(session=sess, book=_mk_book("20240319"), user_message="live", now=datetime(2024, 3, 20, 10, 0))
    assert plan.level == "L0"


def test_postclose_invalidates_old_run():
    sess = _mk_session()
    sess.active_run_id = "run1"
    sess.active_run_daybook_effective_day = "20240319"
    sess.active_run_pulse_trade_day = "20240319"
    sess.active_run_pulse_slot_at = "2024-03-19 14:55:00"
    plan = make_refresh_plan(session=sess, book=_mk_book("20240320"), user_message="今天给我 3 只", now=datetime(2024, 3, 20, 15, 1))
    assert plan.market_phase == PHASE_POSTCLOSE_PENDING
    assert plan.invalidate_active_run is True


def test_weekend_has_no_fake_today_pulse():
    ms = compute_market_state(datetime(2024, 3, 23, 10, 0))
    assert ms.market_phase == PHASE_NON_TRADING
    assert ms.target_pulse_trade_day is None
