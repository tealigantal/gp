from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from gp_assistant.application.daily_refresh import DailyEvidenceRefresher
from gp_assistant.application.real_producer import RealRecommendationProducer
from gp_assistant.cli import _worker_tick
from gp_assistant.contracts.market import TradingCalendarRef
from gp_assistant.store import ContractStore


TZ = ZoneInfo("Asia/Shanghai")


class _Calendar:
    ref = TradingCalendarRef(calendar_id="cn-a", revision="fixture", source="fixture")

    @staticmethod
    def is_open(day: date) -> bool:
        return day == date(2026, 7, 24)

    @staticmethod
    def next_open_after(_day: date) -> date:
        return date(2026, 7, 27)

    @staticmethod
    def previous_open_before(day: date) -> date:
        return date(2026, 7, 24) if day == date(2026, 7, 27) else date(2026, 7, 23)


def _spot(*, resumed: bool = False) -> pd.DataFrame:
    second = 8.0 if resumed else 0.0
    return pd.DataFrame(
        [
            {"code": "000001", "name": "A", "prev_close": 10.0, "price": 10.2, "open": 10.0, "high": 10.3, "low": 9.9, "volume": 100.0, "amount": 1000.0},
            {"code": "000002", "name": "B", "prev_close": 8.0, "price": second, "open": second, "high": second, "low": second, "volume": 10.0 if resumed else 0.0, "amount": 80.0 if resumed else 0.0},
        ]
    )


def _meta(*, stale: bool = False, source: str = "akshare:sina") -> dict[str, object]:
    return {
        "source": source,
        "fallback": False,
        "stale": stale,
        "missing": False,
        "snapshot_session_date": "2026-07-24",
    }


def test_nonempty_old_frame_is_not_target_date_success(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))

    class Provider:
        def get_daily_batch(self, symbols, _start, _end):
            return {symbol: pd.DataFrame([{"date": pd.Timestamp("2026-07-23"), "close": 1.0}]) for symbol in symbols}

    report = DailyEvidenceRefresher(Provider()).refresh(
        symbols=["000001"],
        start="2026-07-24",
        end="2026-07-24",
        target_date="2026-07-24",
    )

    assert report == {"requested": 1, "fetched_nonempty": 1, "target_present": 0, "failed": 0}


def test_same_day_zero_trade_symbol_is_excluded_but_raw_total_is_preserved(tmp_path, monkeypatch):
    before = {
        "000001": {"date": "2026-07-23", "amount": 1000.0},
        "000002": {"date": "2026-07-23", "amount": 800.0},
    }
    after = {
        "000001": {"date": "2026-07-24", "amount": 1100.0},
        "000002": {"date": "2026-07-23", "amount": 800.0},
    }
    rows = iter((before, after))
    monkeypatch.setattr("gp_assistant.application.real_producer.latest_rows", lambda: next(rows))
    monkeypatch.setattr("gp_assistant.application.real_producer.history_frames", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("gp_assistant.application.real_producer.load_cn_a_calendar", lambda: _Calendar())

    class Refresher:
        def __init__(self):
            self.calls = []

        def refresh(self, **kwargs):
            self.calls.append(kwargs)
            return {"requested": 1, "fetched_nonempty": 1, "target_present": 1, "failed": 0}

    refresher = Refresher()
    command = RealRecommendationProducer(
        ContractStore(tmp_path / "contracts.db"),
        spot_loader=_spot,
        spot_meta_loader=_meta,
        daily_refresher=refresher,
    ).produce(datetime(2026, 7, 24, 16, 40, tzinfo=TZ), refresh_daily=True)

    assert refresher.calls[0]["symbols"] == ["000001"]
    assert refresher.calls[0]["target_date"] == "2026-07-24"
    assert command.plan.daily_evidence_date == date(2026, 7, 24)
    assert command.plan.candidate_universe.total_count == 2
    assert command.plan.candidate_universe.eligible_count == 1
    assert command.plan.candidate_universe.complete is True


def test_stale_snapshot_cannot_exclude_and_resumed_stock_reenters_expected_set():
    eligible = frozenset({"000001", "000002"})
    now = datetime(2026, 7, 24, 16, 40, tzinfo=TZ)

    stale = RealRecommendationProducer._no_bar_expected_symbols(
        _spot(), eligible_symbols=eligible, snapshot_meta=_meta(stale=True), now=now,
        required_daily_date=date(2026, 7, 24), is_open=True,
    )
    resumed = RealRecommendationProducer._no_bar_expected_symbols(
        _spot(resumed=True), eligible_symbols=eligible, snapshot_meta=_meta(), now=now,
        required_daily_date=date(2026, 7, 24), is_open=True,
    )

    assert stale == frozenset()
    assert resumed == frozenset()


def test_universe_identity_does_not_change_with_poll_route(tmp_path, monkeypatch):
    rows = {"000001": {"date": "2026-07-24", "amount": 1000.0}, "000002": {"date": "2026-07-24", "amount": 800.0}}
    monkeypatch.setattr("gp_assistant.application.real_producer.latest_rows", lambda: rows)
    monkeypatch.setattr("gp_assistant.application.real_producer.history_frames", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("gp_assistant.application.real_producer.load_cn_a_calendar", lambda: _Calendar())
    store = ContractStore(tmp_path / "contracts.db")
    first = RealRecommendationProducer(store, spot_loader=lambda: _spot(resumed=True), spot_meta_loader=lambda: _meta(source="akshare:sina")).produce(datetime(2026, 7, 24, 16, 40, tzinfo=TZ))
    second = RealRecommendationProducer(store, spot_loader=lambda: _spot(resumed=True), spot_meta_loader=lambda: _meta(source="akshare:em")).produce(datetime(2026, 7, 24, 16, 41, tzinfo=TZ))
    assert first.plan.candidate_universe.content_digest == second.plan.candidate_universe.content_digest
    assert first.plan.plan_id == second.plan.plan_id


def test_failed_plan_attempt_is_throttled_from_completion(tmp_path):
    class FailingPlan:
        count = 0

        def produce(self, *_args, **_kwargs):
            self.count += 1
            raise RuntimeError("source_down")

    class Calls:
        count = 0

        def produce(self, *_args, **_kwargs):
            self.count += 1
            return SimpleNamespace(state="unavailable", reason="fixture")

    plan = FailingPlan()
    runtime = Calls()
    lunch = Calls()
    completed = _worker_tick(
        ContractStore(tmp_path / "contracts.db"),
        now=datetime(2026, 7, 24, 10, 0, tzinfo=TZ),
        last_plan_at=None,
        plan_interval_sec=1800,
        real_producer=plan,
        runtime_producer=runtime,
        lunch_producer=lunch,
        monotonic_now=lambda: 1_000.0,
    )
    returned = _worker_tick(
        ContractStore(tmp_path / "contracts.db"),
        now=datetime(2026, 7, 24, 10, 1, tzinfo=TZ),
        last_plan_at=completed,
        plan_interval_sec=1800,
        real_producer=plan,
        runtime_producer=runtime,
        lunch_producer=lunch,
        monotonic_now=lambda: 1_060.0,
    )

    assert completed == 1_000.0
    assert returned == completed
    assert plan.count == 1
