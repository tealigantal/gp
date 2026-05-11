from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from gp_assistant.contracts.objects import DayBook, MarketBook, SessionState
from gp_assistant.llm.semantics import SemanticTurnSignals
from gp_assistant.runtime import freshness_policy
import gp_assistant.runtime.market_clock as market_clock
from gp_assistant.runtime.freshness_policy import make_refresh_plan
from gp_assistant.runtime.market_clock import (
    PHASE_NON_TRADING,
    PHASE_OPEN_NO_FIRST_BAR,
    PHASE_POSTCLOSE_PENDING,
    PHASE_PREOPEN,
    compute_market_state,
)


@pytest.fixture(autouse=True)
def _calendar(monkeypatch):
    cal = pd.DataFrame(
        [
            {"cal_date": "20240319", "is_open": 1},
            {"cal_date": "20240320", "is_open": 1},
            {"cal_date": "20240321", "is_open": 1},
            {"cal_date": "20240322", "is_open": 1},
            {"cal_date": "20240323", "is_open": 0},
            {"cal_date": "20240324", "is_open": 0},
            {"cal_date": "20240325", "is_open": 1},
        ]
    )
    monkeypatch.setattr(market_clock, "_load_calendar_df", lambda: cal)


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


def test_intraday_plan_keeps_today_daybook_and_slot(monkeypatch):
    monkeypatch.setattr(freshness_policy, "load_config", lambda: SimpleNamespace(intraday_runtime_enabled=True))
    sess = _mk_session()
    plan = make_refresh_plan(
        session=sess,
        book=_mk_book("20240319"),
        user_message="口语化当前执行状态查询",
        now=datetime(2024, 3, 20, 10, 0),
        semantic_signals=SemanticTurnSignals(refresh_intent="live"),
    )
    assert plan.level == "L1"
    assert plan.target_daybook_effective_day == "20240320"
    assert plan.target_pulse_trade_day == "20240320"


def test_intraday_plan_downgrades_when_runtime_disabled(monkeypatch):
    monkeypatch.setattr(freshness_policy, "load_config", lambda: SimpleNamespace(intraday_runtime_enabled=False))
    sess = _mk_session()
    plan = make_refresh_plan(
        session=sess,
        book=_mk_book("20240319"),
        user_message="口语化当前执行状态查询",
        now=datetime(2024, 3, 20, 10, 0),
        semantic_signals=SemanticTurnSignals(refresh_intent="live"),
    )
    assert plan.level == "L0"


def test_postclose_invalidates_old_run():
    sess = _mk_session()
    sess.active_run_id = "run1"
    sess.active_run_daybook_effective_day = "20240319"
    sess.active_run_pulse_trade_day = "20240319"
    sess.active_run_pulse_slot_at = "2024-03-19 14:55:00"
    plan = make_refresh_plan(
        session=sess,
        book=_mk_book("20240320"),
        user_message="口语化重新生成计划查询",
        now=datetime(2024, 3, 20, 15, 1),
        semantic_signals=SemanticTurnSignals(refresh_intent="rebuild"),
    )
    assert plan.market_phase == PHASE_POSTCLOSE_PENDING
    assert plan.invalidate_active_run is True


def test_weekend_has_no_fake_today_pulse():
    ms = compute_market_state(datetime(2024, 3, 23, 10, 0))
    assert ms.market_phase == PHASE_NON_TRADING
    assert ms.target_pulse_trade_day is None
