from __future__ import annotations

from datetime import date, datetime, time as clock_time
import json
import multiprocessing
from pathlib import Path
from typing import Callable

import pandas as pd

from ..contracts.catalog import MarketPhase
from ..contracts.publication_policy import publication_ineligibility
from ..core.config import load_config
from ..providers.boards import is_mainboard
from ..providers.factory import get_provider
from ..store import ContractStore, PublicationConflict
from .daily_refresh import DailyEvidenceRefresher
from .daily_anomalies import lifecycle_exclusions
from .history_daily import coverage_for_date, latest_daily_date
from .lunch_rebalance_producer import LunchRebalanceProducer
from .market_runs import DailyRun, FrozenUniverse, MarketRunStore, RUN_COMPLETE, universe_digest
from .official_suspension import OfficialSuspensionEvidenceCollector
from .publication_service import PublicationService
from .real_producer import RealRecommendationProducer
from .runtime_producer import RuntimeRecommendationProducer, market_phase
from ..serenity.service import FIXED_WEIGHT, load_decision, publish_target
from .trading_calendar import CnATradingCalendar, load_cn_a_calendar


_FREEZE_START = clock_time(14, 57)
_SOURCE_PROBE_START = clock_time(15, 5)
_DAILY_FETCH_START = clock_time(15, 20)
# A next-session base plan is meaningful as soon as the preceding session's
# exact daily evidence is complete.  The window deliberately crosses
# midnight: a recovery that finishes overnight must not wait until the next
# session has already started.
_BASE_PLAN_AFTER_CLOSE_START = clock_time(15, 20)
_BASE_PLAN_PREOPEN_END = clock_time(9, 30)
_MAX_OFFICIAL_SUSPENSION_CANDIDATES = 10
_MAX_DEGRADED_PROVIDER_GAPS = 3


class MarketClock:
    """Named market-day windows; scheduling never depends on tick frequency."""

    @staticmethod
    def local_time(now: datetime) -> clock_time:
        return now.timetz().replace(tzinfo=None)

    @classmethod
    def can_freeze(cls, now: datetime) -> bool:
        value = cls.local_time(now)
        return _FREEZE_START <= value < clock_time(15, 0)

    @classmethod
    def can_probe_current_daily(cls, now: datetime) -> bool:
        return cls.local_time(now) >= _SOURCE_PROBE_START

    @classmethod
    def can_fetch_current_daily(cls, now: datetime) -> bool:
        return cls.local_time(now) >= _DAILY_FETCH_START

    @classmethod
    def can_build_base_plan(cls, now: datetime) -> bool:
        value = cls.local_time(now)
        return value >= _BASE_PLAN_AFTER_CLOSE_START or value < _BASE_PLAN_PREOPEN_END

    @classmethod
    def can_recover_history(cls, now: datetime) -> bool:
        phase = market_phase(now)
        return phase in {MarketPhase.PREOPEN, MarketPhase.LUNCH, MarketPhase.POSTCLOSE}


def _daily_fetch_worker(
    *,
    run_db: str,
    trade_date: str,
    now_iso: str,
    lease_sec: int,
    suspension_collector: OfficialSuspensionEvidenceCollector | None = None,
) -> None:
    """Complete bounded 100-symbol batches outside the worker heartbeat loop."""
    now = datetime.fromisoformat(now_iso)
    ledger = MarketRunStore(Path(run_db))
    token = ledger.acquire_lease(name=f"daily-run:{trade_date}", now=now, lease_sec=lease_sec)
    if token is None:
        return
    cfg = load_config()
    try:
        run = ledger.get_run(trade_date)
        if run is None or run.state == RUN_COMPLETE:
            return
        target = run.trade_date
        lifecycle = lifecycle_exclusions(trade_date=date.fromisoformat(target), symbols=tuple(run.universe.raw_symbols))
        if lifecycle:
            run = ledger.exclude_lifecycle_symbols(trade_date=target, exclusions=lifecycle, now=now)
        expected = ledger.expected_symbols(target)
        present = coverage_for_date(expected, target_date=target)
        missing = ledger.update_coverage(trade_date=target, target_date=target, rows=present, now=now)
        if not missing:
            ledger.complete(target, now)
            return
        ledger.set_source_ready(target, now)
        refresher = DailyEvidenceRefresher(get_provider(prefer="akshare"))
        source = "akshare:" + ">".join(cfg.ak_daily_priority)
        attempted_this_execution: set[str] = set()
        # The parent worker is already isolated from this child process.  A
        # wall-clock budget for the *entire* market was therefore the wrong
        # failure boundary: it cut a healthy 3,000-symbol scan after 15
        # minutes, then imposed an artificial retry wait.  Continue through
        # every not-yet-attempted symbol, persist after each batch, and leave
        # retry only for the genuinely unresolved residue.  Individual source
        # calls retain their provider request timeout and bounded routes.
        while missing:
            batch = tuple(symbol for symbol in missing if symbol not in attempted_this_execution)[:cfg.market_run_batch_size]
            if not batch:
                break
            attempted_this_execution.update(batch)
            attempt_now = datetime.now(now.tzinfo)
            ledger.mark_attempt(trade_date=target, symbols=batch, now=attempt_now, source=source)
            try:
                refresher.refresh(symbols=batch, start=target, end=target, target_date=target)
            except Exception as exc:  # noqa: BLE001
                ledger.mark_attempt_failed(trade_date=target, symbols=batch, now=attempt_now, error=f"{type(exc).__name__}:{exc}")
                break
            present = coverage_for_date(expected, target_date=target)
            missing = ledger.update_coverage(
                trade_date=target,
                target_date=target,
                rows=present,
                now=attempt_now,
                observed_symbols=batch,
            )
            ledger.heartbeat_lease(name=f"daily-run:{trade_date}", token=token, now=attempt_now, lease_sec=lease_sec)
            print(
                json.dumps(
                    {
                        "daily_run_progress": {
                            "trade_date": target,
                            "batch_size": len(batch),
                            "covered": len(expected) - len(missing),
                            "expected": len(expected),
                            "remaining": len(missing),
                        }
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        if not missing:
            ledger.complete(target, datetime.now(now.tzinfo))
            return
        # Daily data remains the primary route.  Only after it has tried every
        # still-missing symbol in this bounded run may an official no-bar fact
        # resolve a small residue.  This never scans the full universe.
        if (
            len(missing) <= _MAX_OFFICIAL_SUSPENSION_CANDIDATES
            and set(missing).issubset(attempted_this_execution)
        ):
            collector = suspension_collector or OfficialSuspensionEvidenceCollector()
            evidence = collector.resolve(
                symbols=tuple(missing),
                trade_date=date.fromisoformat(target),
                observed_at=datetime.now(now.tzinfo),
            )
            if evidence:
                ledger.exclude_verified_suspensions(trade_date=target, evidence_by_symbol=evidence, now=datetime.now(now.tzinfo))
                expected = ledger.expected_symbols(target)
                present = coverage_for_date(expected, target_date=target)
                missing = ledger.update_coverage(
                    trade_date=target,
                    target_date=target,
                    rows=present,
                    now=datetime.now(now.tzinfo),
                )
                if not missing:
                    ledger.complete(target, datetime.now(now.tzinfo))
                    return
        # Persist the completed multi-source failure before asking the
        # bounded degradation policy to decide whether it may be excluded.
        ledger.mark_attempt_failed(trade_date=target, symbols=tuple(missing), now=datetime.now(now.tzinfo), error="provider_empty")
        if len(missing) <= _MAX_DEGRADED_PROVIDER_GAPS:
            degraded = ledger.exclude_retryable_for_degraded(
                trade_date=target, symbols=tuple(missing), now=datetime.now(now.tzinfo)
            )
            expected = ledger.expected_symbols(target)
            present = coverage_for_date(expected, target_date=target)
            missing = ledger.update_coverage(
                trade_date=target, target_date=target, rows=present, now=datetime.now(now.tzinfo)
            )
            if not missing:
                ledger.complete(target, datetime.now(now.tzinfo))
                print(json.dumps({"daily_run_degraded_release": {"trade_date": target, "excluded": len(degraded.universe.excluded_symbols), "remaining": 0}}, ensure_ascii=False), flush=True)
                return
        ledger.record_retry(target, now=datetime.now(now.tzinfo), retry_after_sec=cfg.market_run_retry_interval_sec, error="daily_coverage_incomplete")
    finally:
        ledger.heartbeat_lease(name=f"daily-run:{trade_date}", token=token, now=datetime.now(now.tzinfo), lease_sec=lease_sec)


class MarketDayOrchestrator:
    """The only production authority that schedules market-data side effects."""

    def __init__(
        self,
        store: ContractStore,
        *,
        ledger: MarketRunStore | None = None,
        provider=None,
        real_producer: RealRecommendationProducer | None = None,
        runtime_producer: RuntimeRecommendationProducer | None = None,
        lunch_producer: LunchRebalanceProducer | None = None,
        suspension_collector: OfficialSuspensionEvidenceCollector | None = None,
        spawn_fetch: bool = True,
        process_factory: Callable[..., multiprocessing.Process] = multiprocessing.Process,
    ):
        self.store = store
        self.ledger = ledger or MarketRunStore()
        self.provider = provider
        self.real = real_producer or RealRecommendationProducer(store)
        self.runtime = runtime_producer or RuntimeRecommendationProducer(store)
        self.lunch = lunch_producer or LunchRebalanceProducer(store)
        self.suspension_collector = suspension_collector
        self.spawn_fetch = spawn_fetch
        self.process_factory = process_factory
        self._worker_lease: str | None = None
        self._fetch_process: multiprocessing.Process | None = None

    def tick(self, *, now: datetime) -> dict[str, object]:
        self.ledger.initialize()
        cfg = load_config()
        self._worker_lease = self.ledger.acquire_or_heartbeat_lease(
            name="market-day-orchestrator", token=self._worker_lease, now=now, lease_sec=cfg.market_run_lease_sec
        )
        if self._worker_lease is None:
            return {"state": "standby", "reason": "worker_lease_held"}
        calendar = load_cn_a_calendar()
        self._repair_invalid_current_pointer()
        is_open_session = calendar.is_open(now.date())
        required_date = self._required_daily_date(calendar, now)
        if is_open_session and MarketClock.can_freeze(now):
            self._ensure_run(trade_date=now.date(), now=now, calendar=calendar, reconstructed=False)
        target_run = self._ensure_recovery_queue(required_date=required_date, now=now, calendar=calendar)
        if is_open_session and target_run and target_run.trade_date == now.date().isoformat() and MarketClock.can_probe_current_daily(now):
            target_run = self._finalize_same_day_exclusions(target_run, now=now, calendar=calendar)
        selected = self._select_due_run(target_date=required_date, now=now)
        if selected is not None:
            self._schedule_run(selected, now=now, current_target=required_date.isoformat())
        refreshed_target = self.ledger.get_run(required_date.isoformat())
        if refreshed_target and refreshed_target.state == RUN_COMPLETE:
            self._publish_base_if_due(run=refreshed_target, now=now, calendar=calendar)
        # Historical daily recovery and next-session base publication must be
        # able to finish overnight and over a weekend.  Only same-session
        # freezing, lunch reranking and intraday runtime work require an open
        # exchange session.
        if not is_open_session:
            return {"state": "closed", "market_recovery": self.ledger.health()}
        self._run_lunch_if_due(now=now)
        self._run_runtime_if_due(now=now)
        return {"state": "ok", "market_recovery": self.ledger.health()}

    @staticmethod
    def _required_daily_date(calendar: CnATradingCalendar, now: datetime) -> date:
        before_close = MarketClock.local_time(now) < clock_time(15, 0)
        session = now.date() if calendar.is_open(now.date()) and before_close else calendar.next_open_after(now.date())
        return calendar.previous_open_before(session)

    def _repair_invalid_current_pointer(self) -> None:
        current = self.store.current_publication()
        plan = self.store.load_plan(current.plan_id) if current else None
        if plan is not None and publication_ineligibility(plan) is None:
            return
        fallback = self.store.latest_eligible_publication()
        if fallback is not None and (current is None or current.publication_id != fallback.publication_id):
            self.store.restore_current_publication(fallback.publication_id)

    def _ensure_recovery_queue(self, *, required_date: date, now: datetime, calendar: CnATradingCalendar) -> DailyRun:
        target = self._ensure_run(trade_date=required_date, now=now, calendar=calendar, reconstructed=required_date != now.date())
        checkpoint = self.ledger.last_complete_trade_date()
        anchor = date.fromisoformat(checkpoint) if checkpoint else None
        if anchor is None:
            inferred = latest_daily_date()
            anchor = date.fromisoformat(inferred) if inferred else required_date
        if anchor < required_date:
            for day in calendar.open_days_between(calendar.next_open_after(anchor), required_date):
                self._ensure_run(trade_date=day, now=now, calendar=calendar, reconstructed=day != now.date())
        return target

    def _ensure_run(self, *, trade_date: date, now: datetime, calendar: CnATradingCalendar, reconstructed: bool) -> DailyRun:
        existing = self.ledger.get_run(trade_date.isoformat())
        if existing is not None:
            return existing
        reconstructed = reconstructed or (
            trade_date == now.date() and MarketClock.local_time(now) >= clock_time(15, 0)
        )
        universe = self._freeze_universe(trade_date=trade_date, now=now, calendar=calendar, reconstructed=reconstructed)
        return self.ledger.ensure_run(universe=universe, now=now)

    def _freeze_universe(self, *, trade_date: date, now: datetime, calendar: CnATradingCalendar, reconstructed: bool) -> FrozenUniverse:
        provider = self.provider or get_provider(prefer="akshare")
        spot = provider.get_spot_snapshot()
        snapshot_meta = dict(provider.last_snapshot_meta() or {})
        if not isinstance(spot, pd.DataFrame) or spot.empty or not {"code", "name"}.issubset(spot.columns):
            raise ValueError("candidate_universe_unavailable")
        raw = tuple(sorted({
            str(row.code).zfill(6)
            for row in spot[["code", "name"]].itertuples(index=False)
            if is_mainboard(str(row.code)) and "ST" not in str(row.name).upper() and "退" not in str(row.name)
        }))
        if not raw:
            raise ValueError("candidate_universe_empty")
        same_day = trade_date == now.date()
        excluded = (
            RealRecommendationProducer._no_bar_expected_symbols(
                spot, eligible_symbols=frozenset(raw), snapshot_meta=snapshot_meta, now=now,
                required_daily_date=trade_date, is_open=calendar.is_open(now.date()),
            )
            # A post-close recovery run can be reconstructed only because the
            # 14:57 denominator freeze was missed.  That provenance must stay
            # visible, but it does not make a *fresh, target-session* all-zero
            # spot fact stale or ambiguous.  The predicate above still rejects
            # fallback, stale, cross-day and incomplete snapshots; historical
            # reconstructed runs remain ineligible through ``same_day``.
            if same_day and MarketClock.local_time(now) >= clock_time(15, 0)
            else frozenset()
        )
        expected = tuple(symbol for symbol in raw if symbol not in excluded)
        origin = "reconstructed_current_universe" if reconstructed else "frozen_market_snapshot"
        source = f"{origin}:{snapshot_meta.get('cache_of') or snapshot_meta.get('source') or 'unknown'}"
        return FrozenUniverse(
            trade_date=trade_date.isoformat(), raw_symbols=raw, expected_symbols=expected, excluded_symbols=tuple(sorted(excluded)),
            content_digest=universe_digest(trade_date=trade_date.isoformat(), raw_symbols=raw, expected_symbols=expected, excluded_symbols=tuple(sorted(excluded))),
            source=source, snapshot_meta=snapshot_meta, approximate=reconstructed, captured_at=now.isoformat(),
        )

    def _finalize_same_day_exclusions(self, run: DailyRun, *, now: datetime, calendar: CnATradingCalendar) -> DailyRun:
        # ``approximate`` describes the denominator capture, not the quality
        # of a later same-session no-trade fact.  Recheck an unfinished current
        # day with the original provenance intact; never apply this path to an
        # historical reconstructed run.
        if run.state == RUN_COMPLETE or run.trade_date != now.date().isoformat():
            return run
        universe = self._freeze_universe(
            trade_date=date.fromisoformat(run.trade_date),
            now=now,
            calendar=calendar,
            reconstructed=run.universe.approximate,
        )
        updated = self.ledger.replace_universe_before_fetch(universe=universe, now=now)
        # A same-day no-trade fact can be the final missing evidence.  Re-read
        # the already persisted daily bars immediately instead of leaving a
        # now-complete run behind an obsolete retry timer.
        expected = self.ledger.expected_symbols(updated.trade_date)
        present = coverage_for_date(expected, target_date=updated.trade_date)
        missing = self.ledger.update_coverage(
            trade_date=updated.trade_date,
            target_date=updated.trade_date,
            rows=present,
            now=now,
        )
        if not missing:
            self.ledger.complete(updated.trade_date, now)
            return self.ledger.get_run(updated.trade_date)  # type: ignore[return-value]
        return self.ledger.get_run(updated.trade_date)  # type: ignore[return-value]

    def _select_due_run(self, *, target_date: date, now: datetime) -> DailyRun | None:
        target = self.ledger.get_run(target_date.isoformat())
        if (
            target is not None
            and target.state != RUN_COMPLETE
            and self.ledger.retry_due(target, now)
            and (target.trade_date == now.date().isoformat() or MarketClock.can_recover_history(now))
        ):
            return target
        if not MarketClock.can_recover_history(now):
            return None
        health = self.ledger.health()
        other = self.ledger.get_run(str(health.get("target_trade_date") or ""))
        return other if other and other.state != RUN_COMPLETE and self.ledger.retry_due(other, now) else None

    def _schedule_run(self, run: DailyRun, *, now: datetime, current_target: str) -> None:
        is_current_daily = run.trade_date == now.date().isoformat()
        if is_current_daily and not MarketClock.can_fetch_current_daily(now):
            if MarketClock.can_probe_current_daily(now):
                self._probe_source(run, now=now)
            return
        if is_current_daily and run.source_ready_at is None:
            if not self._probe_source(run, now=now):
                return
        if self._fetch_process is not None and self._fetch_process.is_alive():
            return
        cfg = load_config()
        if self.spawn_fetch:
            process = self.process_factory(
                target=_daily_fetch_worker,
                kwargs={"run_db": str(self.ledger.path), "trade_date": run.trade_date, "now_iso": now.isoformat(), "lease_sec": cfg.market_run_lease_sec},
                name=f"gp-daily-{run.trade_date}", daemon=True,
            )
            process.start()
            self._fetch_process = process
        else:
            _daily_fetch_worker(
                run_db=str(self.ledger.path),
                trade_date=run.trade_date,
                now_iso=now.isoformat(),
                lease_sec=cfg.market_run_lease_sec,
                suspension_collector=self.suspension_collector,
            )

    def _probe_source(self, run: DailyRun, *, now: datetime) -> bool:
        cfg = load_config()
        sample = list(self.ledger.expected_symbols(run.trade_date)[:3])
        if not sample:
            self.ledger.record_probe_wait(run.trade_date, now=now, retry_after_sec=cfg.market_run_probe_interval_sec, error="daily_universe_empty")
            return False
        try:
            frames = (self.provider or get_provider(prefer="akshare")).get_daily_batch(sample, run.trade_date, run.trade_date)
            ready = 0
            for frame in frames.values():
                if not isinstance(frame, pd.DataFrame) or frame.empty:
                    continue
                fields = {"date", "open", "high", "low", "close", "volume", "amount"}
                if not fields.issubset(frame.columns):
                    continue
                if any(str(value)[:10] == run.trade_date for value in frame["date"]):
                    ready += 1
            if ready == len(sample):
                self.ledger.set_source_ready(run.trade_date, now)
                return True
            self.ledger.record_probe_wait(run.trade_date, now=now, retry_after_sec=cfg.market_run_probe_interval_sec, error="daily_source_not_ready")
        except Exception as exc:  # noqa: BLE001
            self.ledger.record_probe_wait(run.trade_date, now=now, retry_after_sec=cfg.market_run_probe_interval_sec, error=f"daily_probe_error:{type(exc).__name__}")
        return False

    def _publish_base_if_due(self, *, run: DailyRun, now: datetime, calendar: CnATradingCalendar) -> None:
        required = self._required_daily_date(calendar, now)
        if run.trade_date != required.isoformat():
            return
        current = self.store.current_publication()
        current_plan = self.store.load_plan(current.plan_id) if current else None
        target_session = now.date() if MarketClock.local_time(now) < clock_time(15, 0) else calendar.next_open_after(now.date())
        if current_plan and current_plan.market_session_date == target_session and current_plan.daily_evidence_date == required and publication_ineligibility(current_plan) is None:
            # A zero-weight base plan is intentionally publishable while the
            # isolated Serenity collector works.  Once that *same frozen*
            # target has an exact complete batch, however, it must be allowed
            # to create its one 3% successor.  Treating matching dates as an
            # unconditional no-op would strand the plan forever at 0%.
            if not self._serenity_upgrade_available(current_plan, now=now):
                return
        # A completed run may finish after midnight during self-healing.  It
        # still belongs to the upcoming session and must publish before that
        # session opens, rather than waiting for a stale 09:20 retry slot.
        if not MarketClock.can_build_base_plan(now):
            return
        command = self.real.produce(now, frozen_universe=run.universe)
        # Producing a complete full-market plan can take minutes.  Admission at
        # the beginning is not sufficient: a 09:29 start must not move the
        # public pointer after the 09:30 pre-open deadline.  The immutable plan
        # may remain as an unpinned audit artifact, but only a completion that
        # is still in the allowed window can become current.
        published_at = datetime.now(now.tzinfo)
        if not MarketClock.can_build_base_plan(published_at):
            print(
                json.dumps(
                    {
                        "base_plan_unpublished": "generation_window_closed",
                        "plan_id": command.plan.plan_id,
                        "started_at": now.isoformat(),
                        "finished_at": published_at.isoformat(),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return
        PublicationService(self.store).publish(plan_id=command.plan.plan_id, runtime_id=None, published_at=published_at)

    @staticmethod
    def _serenity_upgrade_available(plan, *, now: datetime) -> bool:
        """Return true only for a matching, complete 0% → 3% batch upgrade.

        This is a worker-only read/publish-target operation.  It never
        collects a document and a failure deliberately leaves the already
        valid zero-weight plan untouched.
        """
        if float(plan.serenity.applied_weight) >= FIXED_WEIGHT:
            return False
        finalists = tuple(
            item
            for item in plan.evaluated_candidates
            if any(expert.expert == "serenity" for expert in item.experts)
        )
        if not finalists or plan.daily_evidence_date is None:
            return False
        base_scores = {
            item.symbol: round(
                float(item.adaptive_score)
                - sum(float(expert.contribution) for expert in item.experts if expert.expert == "intraday_5m"),
                12,
            )
            for item in finalists
        }
        try:
            target = publish_target(
                (item.symbol for item in finalists),
                market_session_date=plan.market_session_date.isoformat(),
                daily_evidence_date=plan.daily_evidence_date.isoformat(),
                universe_digest=plan.candidate_universe.content_digest,
                base_scores=base_scores,
                observed_at=now.isoformat(),
            )
            return load_decision(target).applied_weight == FIXED_WEIGHT
        except Exception as exc:  # noqa: BLE001
            # Serenity availability may never block or invalidate the base
            # plan.  The child reports collection failures, while this log
            # makes a target/decision mismatch observable to the operator
            # instead of silently stranding an otherwise valid 0% plan.
            print(
                json.dumps(
                    {
                        "serenity_upgrade_skipped": type(exc).__name__,
                        "market_session_date": plan.market_session_date.isoformat(),
                        "daily_evidence_date": plan.daily_evidence_date.isoformat(),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return False

    def _run_runtime_if_due(self, *, now: datetime) -> None:
        if market_phase(now) not in {MarketPhase.MORNING, MarketPhase.AFTERNOON, MarketPhase.CLOSING_AUCTION}:
            return
        current = self.store.current_publication()
        plan = self.store.load_plan(current.plan_id) if current else None
        if plan is None or plan.market_session_date != now.date() or publication_ineligibility(plan) is not None:
            return
        try:
            runtime = self.runtime.produce(now=now, plan_id=plan.plan_id)
            PublicationService(self.store).publish(
                plan_id=plan.plan_id, runtime_id=runtime.runtime_id, published_at=now,
                expected_current_publication_id=current.publication_id,
            )
        except (PublicationConflict, ValueError) as exc:
            print(json.dumps({"runtime_skipped": str(exc)}, ensure_ascii=False), flush=True)

    def _run_lunch_if_due(self, *, now: datetime) -> None:
        if market_phase(now) is not MarketPhase.LUNCH or self.ledger.lunch_state(now.date().isoformat()) is not None:
            return
        result = self.lunch.produce(now=now)
        if result.state == "ready" and result.plan_id and result.runtime_id and result.base_publication_id:
            try:
                publication = PublicationService(self.store).publish(
                    plan_id=result.plan_id, runtime_id=result.runtime_id, published_at=now,
                    expected_current_publication_id=result.base_publication_id,
                )
                self.ledger.mark_lunch(trade_date=now.date().isoformat(), state="published", plan_id=publication.plan_id, now=now)
                return
            except (PublicationConflict, ValueError):
                result = result.__class__("unavailable", result.plan_id, result.runtime_id, None, result.batch_digest, "stale_base_publication")
        self.ledger.mark_lunch(trade_date=now.date().isoformat(), state=result.state, plan_id=result.plan_id, now=now)
