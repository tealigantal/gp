from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from gp_assistant.application.daily_refresh import DailyEvidenceRefresher
from gp_assistant.application.market_orchestrator import MarketClock, MarketDayOrchestrator, _daily_fetch_worker
from gp_assistant.application.market_runs import FrozenUniverse, MarketRunStore, universe_digest
from gp_assistant.application.official_suspension import OfficialSuspensionEvidenceCollector
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


def test_interrupted_run_retries_only_uncovered_symbols(tmp_path, monkeypatch):
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
        rows={symbol: {"date": "2026-07-24", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "amount": 1} for symbol in run.universe.expected_symbols},
        now=now,
        observed_symbols=missing,
    ) == ()
    assert {item.symbol: item.status for item in ledger.symbols(run.trade_date)} == {"000001": "fetched", "000002": "fetched"}

    class Provider:
        def get_daily_batch(self, symbols, _start, _end):
            return {symbol: pd.DataFrame() for symbol in symbols}

    class Collector:
        def resolve(self, *, symbols, trade_date, observed_at):
            assert symbols == ("000002",)
            return {
                "000002": {
                    "symbol": "000002", "trade_date": trade_date.isoformat(), "state": "verified_suspended",
                    "source": "cninfo+szse", "source_record_id": "fixture-announcement", "source_url": "https://official.example/fixture.pdf",
                    "published_at": "2026-07-24T08:00:00+08:00", "content_digest": "fixture-digest",
                    "effective_suspension_date": "2026-07-24", "verification_basis": "szse_announcement_id",
                    "verified_at": observed_at.isoformat(), "excerpt": "自2026年7月24日开市起停牌",
                }
            }

    worker_now = datetime.now(TZ)
    recovery_ledger = MarketRunStore(tmp_path / "recovery_market_runs.db")
    recovery_ledger.ensure_run(universe=_frozen(), now=worker_now)
    monkeypatch.setattr("gp_assistant.application.market_orchestrator.get_provider", lambda **_kwargs: Provider())
    monkeypatch.setattr(
        "gp_assistant.application.market_orchestrator.coverage_for_date",
        lambda symbols, **_kwargs: {"000001": {"date": "2026-07-24"}} if "000001" in symbols else {},
    )
    _daily_fetch_worker(
        run_db=str(recovery_ledger.path), trade_date="2026-07-24", now_iso=worker_now.isoformat(), lease_sec=90,
        suspension_collector=Collector(),
    )
    completed = recovery_ledger.get_run("2026-07-24")
    assert completed is not None and completed.state == "complete"
    assert completed.universe.expected_symbols == ("000001",)
    exclusion = next(item for item in recovery_ledger.symbols("2026-07-24") if item.symbol == "000002")
    assert exclusion.status == "excluded" and exclusion.reason == "official_suspension"
    assert exclusion.evidence is not None and exclusion.evidence["source_record_id"] == "fixture-announcement"

    symbols = tuple(f"{number:06d}" for number in range(1, 102))
    full_universe = FrozenUniverse(
        trade_date="2026-07-24", raw_symbols=symbols, expected_symbols=symbols, excluded_symbols=(),
        content_digest=universe_digest(trade_date="2026-07-24", raw_symbols=symbols, expected_symbols=symbols, excluded_symbols=()),
        source="frozen_market_snapshot:fixture", snapshot_meta={"source": "fixture"}, approximate=False,
        captured_at="2026-07-24T14:57:00+08:00",
    )

    class BatchesProvider:
        def __init__(self):
            self.batches: list[tuple[str, ...]] = []

        def get_daily_batch(self, symbols, _start, _end):
            self.batches.append(tuple(symbols))
            return {symbol: pd.DataFrame() for symbol in symbols}

    class PastFormerBudgetClock:
        calls = 0

        @staticmethod
        def fromisoformat(value):
            return datetime.fromisoformat(value)

        @classmethod
        def now(cls, tz=None):
            cls.calls += 1
            value = worker_now if cls.calls <= 2 else worker_now + timedelta(seconds=901)
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    continuous_ledger = MarketRunStore(tmp_path / "continuous_market_runs.db")
    continuous_ledger.ensure_run(universe=full_universe, now=worker_now)
    batches_provider = BatchesProvider()
    monkeypatch.setattr("gp_assistant.application.market_orchestrator.datetime", PastFormerBudgetClock)
    monkeypatch.setattr("gp_assistant.application.market_orchestrator.get_provider", lambda **_kwargs: batches_provider)
    monkeypatch.setattr("gp_assistant.application.market_orchestrator.coverage_for_date", lambda *_args, **_kwargs: {})
    _daily_fetch_worker(
        run_db=str(continuous_ledger.path), trade_date="2026-07-24", now_iso=worker_now.isoformat(), lease_sec=90,
    )
    assert [len(batch) for batch in batches_provider.batches] == [100, 1]
    assert all(item.attempts == 1 for item in continuous_ledger.symbols("2026-07-24"))


def test_stale_snapshot_cannot_exclude_and_resumed_stock_reenters_expected_set(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))
    eligible = frozenset({"000001", "000002"})
    now = datetime(2026, 7, 24, 16, 40, tzinfo=TZ)
    stale = RealRecommendationProducer._no_bar_expected_symbols(_spot(), eligible_symbols=eligible, snapshot_meta=_meta(stale=True), now=now, required_daily_date=date(2026, 7, 24), is_open=True)
    resumed = RealRecommendationProducer._no_bar_expected_symbols(_spot(resumed=True), eligible_symbols=eligible, snapshot_meta=_meta(), now=now, required_daily_date=date(2026, 7, 24), is_open=True)
    assert stale == frozenset()
    assert resumed == frozenset()

    class Client:
        def load_stock_map(self):
            return {"000002": {"org_id": "fixture"}}

        def fetch_symbol(self, *_args, **_kwargs):
            return {
                "complete": True,
                "backlog": False,
                "records": [{
                    "symbol": "000002", "title": "关于继续停牌的公告", "published_at": "2026-07-24T08:00:00+08:00",
                    "source_record_id": "fixture-announcement", "source_url": "https://official.example/fixture.pdf",
                }],
            }

        @staticmethod
        def download_pdf(*_args, **_kwargs):
            return b"fixture-pdf"

    class Verifier:
        @staticmethod
        def verify(*_args, **_kwargs):
            return True

    collector = OfficialSuspensionEvidenceCollector(
        client=Client(), verifier=Verifier(), parser=lambda *_args, **_kwargs: ("此前预计2026年7月24日开市起复牌。公司股票自2026年7月24日开市起继续停牌", "parsed"),
    )
    evidence = collector.resolve(symbols=("000002",), trade_date=date(2026, 7, 24), observed_at=now)
    assert evidence["000002"]["state"] == "verified_suspended"
    assert evidence["000002"]["effective_suspension_date"] == "2026-07-24"

    one_day_halt = OfficialSuspensionEvidenceCollector(
        client=Client(), verifier=Verifier(), parser=lambda *_args, **_kwargs: (
            "停牌日期为2026年7月24日。公司股票将于2026年7月24日停牌1天，2026年7月27日起复牌。",
            "parsed",
        ),
    ).resolve(symbols=("000002",), trade_date=date(2026, 7, 24), observed_at=now)
    assert one_day_halt["000002"]["state"] == "verified_suspended"
    assert "停牌日期为2026年7月24日" in one_day_halt["000002"]["excerpt"]

    no_proof = OfficialSuspensionEvidenceCollector(
        client=Client(), verifier=Verifier(), parser=lambda *_args, **_kwargs: ("公司股票自2026年7月25日开市起继续停牌", "parsed"),
    ).resolve(symbols=("000002",), trade_date=date(2026, 7, 24), observed_at=now)
    assert no_proof == {}

    class SpotProvider:
        @staticmethod
        def get_spot_snapshot():
            return _spot()

        @staticmethod
        def last_snapshot_meta():
            return _meta()

    ledger = MarketRunStore(tmp_path / "reconstructed_same_day_runs.db")
    reconstructed = FrozenUniverse(
        trade_date="2026-07-24", raw_symbols=("000001", "000002"), expected_symbols=("000001", "000002"), excluded_symbols=(),
        content_digest=universe_digest(trade_date="2026-07-24", raw_symbols=("000001", "000002"), expected_symbols=("000001", "000002"), excluded_symbols=()),
        source="reconstructed_current_universe:fixture", snapshot_meta={"source": "fixture"}, approximate=True,
        captured_at="2026-07-24T16:20:00+08:00",
    )
    run = ledger.ensure_run(universe=reconstructed, now=now)
    orchestrator = MarketDayOrchestrator(ContractStore(tmp_path / "reconstructed_contracts.db"), ledger=ledger, provider=SpotProvider(), spawn_fetch=False)
    monkeypatch.setattr(
        "gp_assistant.application.market_orchestrator.coverage_for_date",
        lambda symbols, **_kwargs: {"000001": {"date": "2026-07-24"}} if "000001" in symbols else {},
    )
    finalized = orchestrator._finalize_same_day_exclusions(run, now=now, calendar=_Calendar())
    assert finalized.state == "complete"
    assert finalized.universe.approximate is True
    assert finalized.universe.expected_symbols == ("000001",)
    assert finalized.universe.excluded_symbols == ("000002",)
    states = {item.symbol: (item.status, item.reason) for item in ledger.symbols("2026-07-24")}
    assert states == {"000001": ("fetched", None), "000002": ("excluded", "trusted_no_trade")}

    historical = orchestrator._freeze_universe(trade_date=date(2026, 7, 23), now=now, calendar=_Calendar(), reconstructed=True)
    assert historical.approximate is True
    assert historical.expected_symbols == ("000001", "000002")
    assert historical.excluded_symbols == ()


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


def test_postclose_source_not_ready_only_probes_without_full_market_fetch(tmp_path, monkeypatch):
    # Exact daily evidence can complete after midnight during recovery.  The
    # next-session base plan must remain eligible until the target opens.  The
    # same predicate is checked again after full-market generation, so a
    # 09:29 start cannot publish after the 09:30 deadline.
    assert MarketClock.can_build_base_plan(datetime(2026, 7, 24, 15, 20, tzinfo=TZ))
    assert MarketClock.can_build_base_plan(datetime(2026, 7, 25, 0, 35, tzinfo=TZ))
    assert MarketClock.can_build_base_plan(datetime(2026, 7, 27, 9, 29, tzinfo=TZ))
    assert not MarketClock.can_build_base_plan(datetime(2026, 7, 27, 9, 30, tzinfo=TZ))
    assert not MarketClock.can_build_base_plan(datetime(2026, 7, 27, 14, 59, tzinfo=TZ))

    class SlowRealProducer:
        @staticmethod
        def produce(_now, *, frozen_universe):
            assert frozen_universe == _frozen()
            return type("Command", (), {"plan": type("Plan", (), {"plan_id": "late-plan"})()})()

    class DeadlineClock:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 7, 27, 9, 30, tzinfo=tz)

    publication_store = ContractStore(tmp_path / "deadline-contracts.db")
    deadline_orchestrator = MarketDayOrchestrator(
        publication_store,
        ledger=MarketRunStore(tmp_path / "deadline-market-runs.db"),
        real_producer=SlowRealProducer(),
    )
    monkeypatch.setattr("gp_assistant.application.market_orchestrator.datetime", DeadlineClock)
    deadline_orchestrator._publish_base_if_due(
        run=type("Run", (), {"trade_date": "2026-07-24", "universe": _frozen()})(),
        now=datetime(2026, 7, 27, 9, 29, tzinfo=TZ),
        calendar=_Calendar(),
    )
    assert publication_store.current_publication() is None
    monkeypatch.undo()

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
