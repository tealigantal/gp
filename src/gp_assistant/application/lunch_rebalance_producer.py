from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from hashlib import sha256
import json
import os
from pathlib import Path
import threading

from ..contracts.catalog import MarketPhase, PlanTargetState, RuntimeDataState
from ..contracts.evidence import DecisionPolicyBinding, ProducerIdentity
from ..contracts.market import ResolvedPlanTarget, TradingCalendarRef
from ..contracts.runtime import MarketGate, RuntimeDataQuality, RuntimeObservation, SymbolExecutionState
from ..intraday.lunch_rebalance import (
    LUNCH_POLICY_REVISION,
    LunchBatchUnavailable,
    LunchFiveMinuteBatch,
    collect_lunch_batch,
    collect_lunch_batch_isolated,
    rerank_lunch_candidates,
)
from ..providers.factory import get_provider
from ..store import ContractStore, PublicationConflict
from .plan_service import PlanService
from .publication_service import PublicationService
from .runtime_service import RuntimeService


LUNCH_PRODUCER_NAME = "lunch_5m_producer"
LUNCH_PRODUCER_REVISION = "1"
_PROCESS_LOCK = threading.Lock()
_FINALITY_DELAY = time(11, 32)


class LunchWriteBusy(RuntimeError):
    pass


class _CrossProcessLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise LunchWriteBusy("lunch_write_busy") from exc
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.handle is None:
            return
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


@dataclass(frozen=True)
class LunchRebalanceResult:
    state: str
    plan_id: str | None
    runtime_id: str | None
    publication_id: str | None
    batch_digest: str | None
    reason: str | None = None


def is_lunch_plan(plan) -> bool:
    return bool(plan and plan.producer.name == LUNCH_PRODUCER_NAME)


class LunchRebalanceProducer:
    def __init__(self, store: ContractStore, *, provider=None, batch_loader=None):
        self.store = store
        self.provider = provider
        self.batch_loader = batch_loader

    def produce(self, *, now: datetime) -> LunchRebalanceResult:
        local_time = now.timetz().replace(tzinfo=None)
        if not (_FINALITY_DELAY <= local_time < time(13, 0)):
            return LunchRebalanceResult("skipped", None, None, None, None, "outside_lunch_window")
        with _PROCESS_LOCK:
            publication = self.store.current_publication()
            plan = self.store.load_plan(publication.plan_id) if publication else None
            if plan is None or plan.market_session_date != now.date():
                return LunchRebalanceResult("unavailable", None, None, None, None, "current_base_plan_unavailable")
            if is_lunch_plan(plan):
                return LunchRebalanceResult(
                    "reused",
                    plan.plan_id,
                    publication.runtime_id if publication else None,
                    publication.publication_id if publication else None,
                    plan.producer.source_digest,
                )
            finalist_symbols = frozenset(
                candidate.symbol
                for candidate in plan.evaluated_candidates
                if any(expert.expert == "serenity" for expert in candidate.experts)
            )
            if len(finalist_symbols) != 30:
                return LunchRebalanceResult("unavailable", plan.plan_id, None, publication.publication_id, None, "frozen_top30_unavailable")
            try:
                if self.batch_loader is not None:
                    batch: LunchFiveMinuteBatch = self.batch_loader(
                        self.provider,
                        finalist_symbols,
                        market_session_date=plan.market_session_date,
                        timezone=now.tzinfo,
                        max_workers=3,
                    )
                elif self.provider is not None:
                    batch = collect_lunch_batch(
                        self.provider,
                        finalist_symbols,
                        market_session_date=plan.market_session_date,
                        timezone=now.tzinfo,
                        max_workers=3,
                    )
                else:
                    batch = collect_lunch_batch_isolated(
                        finalist_symbols,
                        market_session_date=plan.market_session_date,
                        timezone_name=getattr(now.tzinfo, "key", "Asia/Shanghai"),
                        budget_sec=int(os.getenv("GP_INTRADAY_FETCH_BUDGET_SEC", "110")),
                    )
            except LunchBatchUnavailable as exc:
                return LunchRebalanceResult("unavailable", plan.plan_id, None, publication.publication_id, None, str(exc))
            if batch.slot_closed_at > now:
                return LunchRebalanceResult("unavailable", plan.plan_id, None, publication.publication_id, None, "lunch_slot_not_closed")
            candidates = rerank_lunch_candidates(
                plan.evaluated_candidates,
                eligible_symbols=finalist_symbols,
                batch=batch,
            )
            source_payload = {
                "base_plan_id": plan.plan_id,
                "batch_digest": batch.content_digest,
                "policy_revision": LUNCH_POLICY_REVISION,
            }
            source_digest = sha256(json.dumps(source_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            lock_path = self.store.path.with_name(f".{self.store.path.name}.lunch-rebalance.lock")
            try:
                with _CrossProcessLock(lock_path):
                    current = self.store.current_publication()
                    if current is None or current.publication_id != publication.publication_id:
                        current_plan = self.store.load_plan(current.plan_id) if current else None
                        if is_lunch_plan(current_plan) and current_plan.producer.source_digest == source_digest:
                            return LunchRebalanceResult(
                                "reused",
                                current_plan.plan_id,
                                current.runtime_id,
                                current.publication_id,
                                batch.content_digest,
                            )
                        return LunchRebalanceResult("unavailable", plan.plan_id, None, current.publication_id if current else None, batch.content_digest, "stale_base_publication")
                    return self._commit(
                        now=now,
                        base_plan=plan,
                        base_publication_id=publication.publication_id,
                        finalist_symbols=finalist_symbols,
                        candidates=candidates,
                        batch=batch,
                        source_digest=source_digest,
                    )
            except LunchWriteBusy as exc:
                return LunchRebalanceResult("unavailable", plan.plan_id, None, publication.publication_id, batch.content_digest, str(exc))

    def _commit(
        self,
        *,
        now: datetime,
        base_plan,
        base_publication_id: str,
        finalist_symbols: frozenset[str],
        candidates,
        batch: LunchFiveMinuteBatch,
        source_digest: str,
    ) -> LunchRebalanceResult:
            target = ResolvedPlanTarget(
                market=base_plan.market,
                market_session_date=base_plan.market_session_date,
                daily_evidence_date=base_plan.daily_evidence_date,
                state=PlanTargetState.READY,
                resolved_at=now,
                calendar=TradingCalendarRef(calendar_id="cn_a", revision="lunch_from_base_v1", source="base_plan"),
            )
            lunch_plan = PlanService(self.store).get_or_create(
                target=target,
                universe=base_plan.candidate_universe,
                policy=DecisionPolicyBinding(
                    revision="adaptive_kernel_v4_lunch_5m",
                    adaptive_policy_state_version=f"{LUNCH_POLICY_REVISION}:{batch.content_digest}",
                    selection_policy="daily_top30_then_lunch_5m_rerank",
                    risk_profile=base_plan.decision_policy.risk_profile,
                ),
                producer=ProducerIdentity(
                    name=LUNCH_PRODUCER_NAME,
                    revision=LUNCH_PRODUCER_REVISION,
                    source_digest=source_digest,
                ),
                evaluated_candidates=candidates,
                serenity=base_plan.serenity,
                generated_at=now,
                selection_eligible_symbols=finalist_symbols,
            ).plan
            ordered_finalists = tuple(
                candidate for candidate in lunch_plan.evaluated_candidates if candidate.symbol in finalist_symbols
            )
            states = tuple(
                SymbolExecutionState(
                    symbol=candidate.symbol,
                    state="ready",
                    vwap=batch.signals[candidate.symbol].vwap_proxy,
                    intraday_score=batch.signals[candidate.symbol].score,
                    reason_codes=batch.signals[candidate.symbol].reason_codes,
                )
                for candidate in ordered_finalists
            )
            observation = RuntimeObservation(
                runtime_id="pending",
                plan_id=lunch_plan.plan_id,
                market=lunch_plan.market,
                market_session_date=lunch_plan.market_session_date,
                observed_at=now,
                slot_closed_at=batch.slot_closed_at,
                market_phase=MarketPhase.LUNCH,
                data_quality=RuntimeDataQuality(
                    state=RuntimeDataState.READY,
                    source=batch.source,
                    reason_codes=(),
                ),
                market_gate=MarketGate(state="deny", score=0.0, reason_codes=("lunch_break",)),
                symbol_execution_states=states,
                producer_name=LUNCH_PRODUCER_NAME,
                producer_revision=LUNCH_PRODUCER_REVISION,
            )
            runtime = RuntimeService(self.store).observe(observation)
            try:
                lunch_publication = PublicationService(self.store).publish(
                    plan_id=lunch_plan.plan_id,
                    runtime_id=runtime.runtime_id,
                    published_at=now,
                    expected_current_publication_id=base_publication_id,
                )
            except PublicationConflict:
                current = self.store.current_publication()
                current_plan = self.store.load_plan(current.plan_id) if current else None
                if is_lunch_plan(current_plan) and current_plan.producer.source_digest == source_digest:
                    return LunchRebalanceResult("reused", current_plan.plan_id, current.runtime_id, current.publication_id, batch.content_digest)
                return LunchRebalanceResult("unavailable", base_plan.plan_id, None, current.publication_id if current else None, batch.content_digest, "stale_base_publication")
            return LunchRebalanceResult(
                "published",
                lunch_plan.plan_id,
                runtime.runtime_id,
                lunch_publication.publication_id,
                batch.content_digest,
            )
