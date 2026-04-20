from datetime import datetime

from gp_assistant.runtime.market_clock import (
    compute_market_state,
    PHASE_PREOPEN,
    PHASE_OPEN_NO_FIRST_BAR,
    PHASE_INTRADAY_AM,
    PHASE_POSTCLOSE_PENDING,
    PHASE_NON_TRADING,
)
from gp_assistant.runtime.freshness_policy import make_refresh_plan
from gp_assistant.contracts.objects import SessionState, DayBook, MarketBook


def _mk_session() -> SessionState:
    now = datetime(2024, 3, 20, 10, 0)
    return SessionState(session_id='s', created_at=str(now), updated_at=str(now))


def _mk_book(day: str = '20240319') -> MarketBook:
    db = DayBook(trading_day=day, generated_at='2024-03-19T16:10:00', regime={}, tradeable=False)
    return MarketBook(trading_day=day, book_version='v1', updated_at='2024-03-19T16:10:00', regime={}, daybook=db)


def test_preopen_uses_previous_completed_daybook():
    # 09:20 local time
    ms = compute_market_state(datetime(2024, 3, 20, 9, 20))
    assert ms.market_phase in {PHASE_PREOPEN}
    # daybook should be previous open day
    assert ms.target_daybook_effective_day < '20240320'


def test_open_no_first_bar_does_not_reuse_yesterday_pulse():
    ms = compute_market_state(datetime(2024, 3, 20, 9, 32))
    assert ms.market_phase == PHASE_OPEN_NO_FIRST_BAR
    assert ms.target_pulse_trade_day == '20240320'
    # no closed 5m slot yet
    assert ms.target_pulse_slot_at is None


def test_intraday_only_refreshes_pulse_level():
    sess = _mk_session()
    book = _mk_book('20240319')
    plan = make_refresh_plan(session=sess, book=book, user_message='现在还能买吗', now=datetime(2024, 3, 20, 10, 0))
    assert plan.level == 'L1'
    assert plan.target_daybook_effective_day == '20240319'
    assert plan.target_pulse_trade_day == '20240320'


def test_postclose_invalidates_old_run():
    sess = _mk_session()
    sess.active_run_id = 'run1'
    sess.active_run_daybook_effective_day = '20240319'
    sess.active_run_pulse_trade_day = '20240319'
    sess.active_run_pulse_slot_at = '2024-03-19 14:55:00'
    plan = make_refresh_plan(session=sess, book=_mk_book('20240320'), user_message='今天给我 3 只', now=datetime(2024, 3, 20, 15, 1))
    assert plan.market_phase == PHASE_POSTCLOSE_PENDING
    assert plan.invalidate_active_run is True


def test_weekend_no_fake_today_pulse():
    # Saturday
    ms = compute_market_state(datetime(2024, 3, 23, 10, 0))
    assert ms.market_phase == PHASE_NON_TRADING
    assert ms.target_pulse_trade_day is None
