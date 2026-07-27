from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from gp_assistant.application.daily_refresh import DailyEvidenceRefresher
from gp_assistant.application.market_orchestrator import MarketDayOrchestrator
from gp_assistant.application.market_runs import FrozenUniverse, MarketRunStore, universe_digest
from gp_assistant.application.real_producer import RealRecommendationProducer
from gp_assistant.contracts.market import TradingCalendarRef
from gp_assistant.store import ContractStore


TZ = ZoneInfo("Asia/Shanghai")


class _Calendar:
    ref = TradingCalendarRef(calendar_id="cn-a", revision="fixture", source="fixture")

    @staticmethod
    def is_open(day: date) -> bool:
        return day in {date(2026, 7, 23), date(2026, 7, 24), date(2026, 7, 27)}

    @staticmethod
    def next_open_after(day: date) -> date:
        return date(2026, 7, 27) if day <= date(2026, 7, 24) else date(2026, 7, 28)

    @staticmethod
    def previous_open_before(day: date) -> date:
        return date(2026, 7, 24) if day >= date(2026, 7, 27) else date(2026, 7, 23)


def _frozen() -> FrozenUniverse:
    raw = ("000001", "000002")
    return FrozenUniverse(
        trade_date="2026-07-24", raw_symbols=raw, expected_symbols=raw, excluded_symbols=(),
        content_digest=universe_digest(trade_date="2026-07-24", raw_symbols=raw, expected_symbols=raw, excluded_symbols=()),
        source="frozen_market_snapshot:fixture", snapshot_meta={"source": "fixture"}, approximate=False,
        captured_at="2026-07-24T14:57:00+08:00",
    )


def _spot(*, resumed: bool = False) -> pd.DataFrame:
    second = 8.0 if resumed else 0.0
    return pd.DataFrame(
        [
            {"code": "000001", "name": "A", "prev_close": 10.0, "price": 10.2, "open": 10.0, "high": 10.3, "low": 9.9, "volume": 100.0, "amount": 1000.0},
            {"code": "000002", "name": "B", "prev_close": 8.0, "price": second, "open": second, "high": second, "low": second, "volume": 10.0 if resumed else 0.0, "amount": 80.0 if resumed else 0.0},
        ]
    )


def _meta(*, stale: bool = False) -> dict[str, object]:
    return {"source": "akshare:sina", "fallback": False, "stale": stale, "missing": False, "snapshot_session_date": "2026-07-24"}


def test_nonempty_old_frame_is_not_target_date_success(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))

    class Provider:
        def get_daily_batch(self, symbols, _start, _end):
            return {symbol: pd.DataFrame([{"date": pd.Timestamp("2026-07-23"), "close": 1.0}]) for symbol in symbols}

    report = DailyEvidenceRefresher(Provider()).refresh(
        symbols=["000001"], start="2026-07-24", end="2026-07-24", target_date="2026-07-24",
    )
    assert report == {"requested": 1, "fetched_nonempty": 1, "target_present": 0, "failed": 0}


def test_interrupted_run_retries_only_uncovered_symbols(tmp_path):
    ledger = MarketRunStore(tmp_path / "market_runs.db")
    now = datetime(2026, 7, 24, 15, 30, tzinfo=TZ)
    run = ledger.ensure_run(universe=_frozen(), now=now)
    missing = ledger.update_coverage(
        trade_date=run.trade_date, target_date=run.trade_date,
        rows={"000001": {"date": "2026-07-24", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "amount": 1}}, now=now,
    )
    assert missing == ("000002",)
    ledger.mark_attempt(trade_date=run.trade_date, symbols=missing, now=now, source="akshare:sina>em>tx")
    assert {item.symbol: item.attempts for item in ledger.symbols(run.trade_date)} == {"000001": 0, "000002": 1}
    assert ledger.update_coverage(
        trade_date=run.trade_date, target_date=run.trade_date,
        rows={symbol: {"date": "2026-07-24", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "amount": 1} for symbol in run.universe.expected_symbols}, now=now,
    ) == ()


def test_stale_snapshot_cannot_exclude_and_resumed_stock_reenters_expected_set():
    eligible = frozenset({"000001", "000002"})
    now = datetime(2026, 7, 24, 16, 40, tzinfo=TZ)
    stale = RealRecommendationProducer._no_bar_expected_symbols(_spot(), eligible_symbols=eligible, snapshot_meta=_meta(stale=True), now=now, required_daily_date=date(2026, 7, 24), is_open=True)
    resumed = RealRecommendationProducer._no_bar_expected_symbols(_spot(resumed=True), eligible_symbols=eligible, snapshot_meta=_meta(), now=now, required_daily_date=date(2026, 7, 24), is_open=True)
    assert stale == frozenset()
    assert resumed == frozenset()


def test_plan_reads_one_frozen_universe_and_never_polls_spot(tmp_path, monkeypatch):
    rows = {symbol: {"date": "2026-07-24", "amount": amount, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for symbol, amount in (("000001", 1000.0), ("000002", 800.0))}
    monkeypatch.setattr("gp_assistant.application.real_producer.coverage_for_date", lambda *_args, **_kwargs: rows)
    monkeypatch.setattr("gp_assistant.application.real_producer.history_frames", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("gp_assistant.application.real_producer.load_cn_a_calendar", lambda: _Calendar())
    called = {"spot": 0}
    command = RealRecommendationProducer(ContractStore(tmp_path / "contracts.db"), spot_loader=lambda: called.__setitem__("spot", called["spot"] + 1)).produce(
        datetime(2026, 7, 24, 16, 40, tzinfo=TZ), frozen_universe=_frozen(),
    )
    assert command.plan.candidate_universe.complete is True
    assert command.plan.candidate_universe.total_count == 2
    assert called["spot"] == 0


def test_postclose_source_not_ready_only_probes_without_full_market_fetch(tmp_path):
    class Provider:
        def __init__(self):
            self.calls = 0

        def get_daily_batch(self, symbols, _start, _end):
            self.calls += 1
            return {symbol: pd.DataFrame() for symbol in symbols}

    now = datetime(2026, 7, 24, 15, 5, tzinfo=TZ)
    ledger = MarketRunStore(tmp_path / "market_runs.db")
    run = ledger.ensure_run(universe=_frozen(), now=now)
    provider = Provider()
    orchestrator = MarketDayOrchestrator(ContractStore(tmp_path / "contracts.db"), ledger=ledger, provider=provider, spawn_fetch=False)
    orchestrator._schedule_run(run, now=now, current_target=run.trade_date)
    updated = ledger.get_run(run.trade_date)
    assert provider.calls == 1
    assert updated is not None and updated.state == "probing"
    assert all(item.attempts == 0 for item in ledger.symbols(run.trade_date))
