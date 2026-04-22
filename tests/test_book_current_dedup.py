from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from gp_assistant.book.engine import book_is_fresh_for_plan
from gp_assistant.contracts.objects import DayBook, MarketBook
from gp_assistant.gateway.app import app
from gp_assistant.gateway import routes
from gp_assistant.runtime.freshness_policy import RefreshPlan


def _plan() -> RefreshPlan:
    return RefreshPlan(
        level='L1',
        scope='watchset',
        target_daybook_effective_day='20240320',
        target_pulse_trade_day='20240320',
        target_pulse_slot_at='2024-03-20T10:00:00+08:00',
        market_phase='INTRADAY_AM',
        data_status='ok',
        invalidate_active_run=False,
        reason_codes=['dashboard'],
        symbols_hint=[],
        calendar_source='exchange',
    )


def _book() -> MarketBook:
    return MarketBook(
        trading_day='20240320',
        book_version='book_1',
        updated_at='2024-03-20T10:00:00+08:00',
        regime={},
        daybook=DayBook(trading_day='20240320', generated_at='2024-03-20T09:00:00+08:00', regime={}),
        board=[],
        watchset=[],
        symbol_states={},
        portfolio_snapshot={},
        last_closed_5m='2024-03-20T10:00:00+08:00',
        side_results=[],
        daybook_effective_day='20240320',
        pulse_trade_day='20240320',
        pulse_slot_at='2024-03-20T10:00:00+08:00',
        market_phase='INTRADAY_AM',
        data_status='ok',
        calendar_source='exchange',
    )


def test_book_is_fresh_for_plan_matches_exact_slot():
    assert book_is_fresh_for_plan(_book(), _plan()) is True


def test_book_is_fresh_for_plan_rejects_slot_mismatch():
    stale = _book().model_copy(update={'pulse_slot_at': '2024-03-20T09:55:00+08:00'})
    assert book_is_fresh_for_plan(stale, _plan()) is False


def test_current_book_skips_rebuild_when_dashboard_book_is_fresh(monkeypatch):
    client = TestClient(app)
    plan = _plan()
    book = _book()

    monkeypatch.setattr(routes, 'make_dashboard_refresh_plan', lambda: plan)
    monkeypatch.setattr(routes, 'load_current_book', lambda: book)

    def _unexpected(_plan: RefreshPlan):
        raise AssertionError('ensure_book should not run for a fresh dashboard book')

    monkeypatch.setattr(routes, 'ensure_book', _unexpected)

    response = client.get('/api/book/current')
    assert response.status_code == 200
    payload = response.json()['book']
    assert payload['book_version'] == book.book_version


def test_current_book_rebuilds_when_dashboard_book_is_stale(monkeypatch):
    client = TestClient(app)
    plan = _plan()
    stale = _book().model_copy(update={'pulse_slot_at': '2024-03-20T09:55:00+08:00'})
    rebuilt = _book().model_copy(update={'book_version': 'book_2', 'updated_at': '2024-03-20T10:01:00+08:00'})

    monkeypatch.setattr(routes, 'make_dashboard_refresh_plan', lambda: plan)
    monkeypatch.setattr(routes, 'load_current_book', lambda: stale)

    calls = {'count': 0}

    def _ensure(refresh_plan: RefreshPlan):
        calls['count'] += 1
        assert refresh_plan == plan
        return rebuilt

    monkeypatch.setattr(routes, 'ensure_book', _ensure)

    response = client.get('/api/book/current')
    assert response.status_code == 200
    payload = response.json()['book']
    assert payload['book_version'] == 'book_2'
    assert calls['count'] == 1
