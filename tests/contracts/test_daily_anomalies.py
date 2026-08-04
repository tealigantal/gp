from datetime import date

from gp_assistant.application.daily_anomalies import classify_missing_daily
from gp_assistant.application.daily_anomalies import lifecycle_exclusions


def test_missing_provider_data_stays_retryable_and_is_not_called_suspension():
    assert classify_missing_daily(
        symbol="603221", trade_date=date(2026, 8, 3), error="sina empty"
    ) == ("retry", "provider_empty")
    assert classify_missing_daily(
        symbol="603221", trade_date=date(2026, 8, 3), error="RemoteDisconnected"
    ) == ("retry", "provider_unavailable")


def test_lifecycle_decision_is_bound_to_target_date():
    assert classify_missing_daily(
        symbol="001232",
        trade_date=date(2026, 8, 3),
        instrument={"listed_from": "2026-08-05"},
        error="empty",
    ) == ("excluded", "pre_listing")
    assert classify_missing_daily(
        symbol="001232",
        trade_date=date(2026, 8, 5),
        instrument={"listed_from": "2026-08-05"},
        error="empty",
    ) == ("retry", "provider_empty")


def test_lifecycle_exclusions_use_target_date(monkeypatch, tmp_path):
    path = tmp_path / "universe" / "instrument_lifecycle.json"
    path.parent.mkdir()
    path.write_text('{"records":[{"symbol":"001232","effective_to":"2026-08-04","reason":"pre_listing"}]}', encoding="utf-8")
    monkeypatch.setattr("gp_assistant.application.daily_anomalies.store_dir", lambda: tmp_path)
    assert lifecycle_exclusions(trade_date=date(2026, 8, 4), symbols=("001232",))["001232"]["reason"] == "pre_listing"
    assert lifecycle_exclusions(trade_date=date(2026, 8, 5), symbols=("001232",)) == {}
