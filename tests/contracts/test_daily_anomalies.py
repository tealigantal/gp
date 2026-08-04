from datetime import date

from gp_assistant.application.daily_anomalies import classify_missing_daily
from gp_assistant.application.daily_anomalies import lifecycle_exclusions
from gp_assistant.application.market_runs import FrozenUniverse, MarketRunStore


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


def test_bounded_provider_gap_can_use_existing_excluded_contract(tmp_path):
    store = MarketRunStore(tmp_path / "market_runs.db")
    universe = FrozenUniverse("2026-08-03", ("000001", "603221"), ("000001", "603221"), (), "d", "fixture", {}, False, "2026-08-03T15:00:00+08:00")
    from datetime import datetime, timezone
    store.ensure_run(universe=universe, now=datetime.now(timezone.utc))
    store.mark_attempt_failed(trade_date="2026-08-03", symbols=("603221",), now=datetime.now(timezone.utc), error="sina empty")
    updated = store.exclude_retryable_for_degraded(trade_date="2026-08-03", symbols=("603221",), now=datetime.now(timezone.utc))
    assert updated.universe.expected_symbols == ("000001",)
    assert next(item for item in store.symbols("2026-08-03") if item.symbol == "603221").reason == "degraded_provider_failure"
