from __future__ import annotations

from fastapi.testclient import TestClient

from gp_assistant.contracts.objects import DayBook, MarketBook
from gp_assistant.gateway import routes
from gp_assistant.gateway.app import app
from gp_assistant.runtime.freshness_policy import RefreshPlan
from gp_assistant.book.engine import book_is_fresh_for_plan


def _plan() -> RefreshPlan:
    return RefreshPlan(
        level="L0",
        scope="none",
        target_daybook_effective_day="20240320",
        target_pulse_trade_day="20240320",
        target_pulse_slot_at="2024-03-20 10:00:00",
        market_phase="INTRADAY_AM",
        data_status="ok",
        invalidate_active_run=False,
        reason_codes=["readonly"],
        symbols_hint=[],
        calendar_source="exchange",
    )


def _book() -> MarketBook:
    return MarketBook(
        trading_day="20240320",
        book_version="slot_artifact_1",
        updated_at="2024-03-20T10:00:00+08:00",
        regime={},
        daybook=DayBook(trading_day="20240320", generated_at="2024-03-20T09:00:00+08:00", regime={}),
        board=[],
        watchset=[],
        symbol_states={},
        portfolio_snapshot={},
        last_closed_5m="2024-03-20T10:00:00+08:00",
        side_results=[],
        artifact_id="slot_artifact_1",
        slot_id="20240320_1000",
        slot_status="OK",
        publish_allowed=True,
        daybook_effective_day="20240320",
        pulse_trade_day="20240320",
        pulse_slot_at="2024-03-20 10:00:00",
        market_phase="INTRADAY_AM",
        data_status="ok",
        calendar_source="exchange",
    )


def test_book_is_fresh_for_plan_matches_exact_slot():
    assert book_is_fresh_for_plan(_book(), _plan()) is True


def test_book_is_fresh_for_plan_ignores_retired_slot_mismatch():
    current = _book().model_copy(update={"pulse_slot_at": "2024-03-20 09:55:00"})
    assert book_is_fresh_for_plan(current, _plan()) is True


def test_current_book_endpoint_is_read_only(monkeypatch):
    client = TestClient(app)
    book = _book()

    monkeypatch.setattr(routes, "load_current_book", lambda: book)

    response = client.get("/api/book/current")
    assert response.status_code == 200
    payload = response.json()["book"]
    assert payload["book_version"] == "slot_artifact_1"
    assert payload["artifact_id"] == "slot_artifact_1"
    assert payload["slot_id"] == "20240320_1000"


def test_slot_endpoint_reads_specific_artifact(monkeypatch):
    client = TestClient(app)
    artifact = {"artifact_id": "slot_1", "slot_id": "20240320_1000", "slot_status": "OK"}

    class _Artifact:
        def model_dump(self):
            return artifact

    monkeypatch.setattr(routes, "load_slot_artifact", lambda artifact_id: _Artifact() if artifact_id == "slot_1" else None)

    response = client.get("/api/book/slot/slot_1")
    assert response.status_code == 200
    assert response.json()["book"]["artifact_id"] == "slot_1"
