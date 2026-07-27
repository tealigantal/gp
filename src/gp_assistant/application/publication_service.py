from __future__ import annotations

import json

from ..contracts.catalog import ExecutionStatus
from ..contracts.ids import content_id
from ..contracts.publication import PublicationDecision, PublicationLineage, RecommendationPublication
from ..contracts.publication_policy import require_publication_eligible
from ..store import ContractStore


class PublicationService:
    def __init__(self, store: ContractStore):
        self.store = store

    def publish(
        self,
        *,
        plan_id: str,
        runtime_id: str | None,
        published_at,
        expected_current_publication_id: str | None | object = ...,
    ) -> RecommendationPublication:
        current = self.store.current_publication()
        plan = self.store.load_plan(plan_id)
        if plan is None:
            raise ValueError("plan_not_found")
        require_publication_eligible(plan)
        runtime = self.store.load_runtime(runtime_id) if runtime_id else None
        if runtime_id and runtime is None:
            raise ValueError("runtime_plan_mismatch")
        if runtime and runtime.plan_id != plan.plan_id:
            raise ValueError("runtime_plan_mismatch")
        if runtime and runtime.market_session_date != plan.market_session_date:
            raise ValueError("runtime_session_mismatch")
        if current:
            current_plan = self.store.load_plan(current.plan_id)
            current_runtime = self.store.load_runtime(current.runtime_id) if current.runtime_id else None
            if current_plan and plan.market_session_date < current_plan.market_session_date:
                raise ValueError("stale_publication_write")
            if current_plan and plan.market_session_date == current_plan.market_session_date:
                current_evidence = current_plan.daily_evidence_date
                target_evidence = plan.daily_evidence_date
                if current_evidence is not None and (target_evidence is None or target_evidence < current_evidence):
                    raise ValueError("stale_publication_write")
                if plan.generated_at < current_plan.generated_at:
                    raise ValueError("stale_publication_write")
                if current_plan.producer.name == "lunch_5m_producer" and plan.producer.name != "lunch_5m_producer":
                    raise ValueError("stale_publication_write")
                if current.plan_id == plan.plan_id and current_runtime is not None and runtime is None:
                    raise ValueError("stale_publication_write")
                if current_runtime is not None and runtime is not None:
                    current_slot = current_runtime.slot_closed_at or current_runtime.observed_at
                    target_slot = runtime.slot_closed_at or runtime.observed_at
                    if target_slot < current_slot or runtime.observed_at < current_runtime.observed_at:
                        raise ValueError("stale_publication_write")
        execution_status = ExecutionStatus.AVAILABLE if runtime and runtime.data_quality.state.value == "ready" else ExecutionStatus.PENDING if runtime is None else ExecutionStatus.UNAVAILABLE
        tradeable = bool(plan.decision.status.value == "recommend" and execution_status is ExecutionStatus.AVAILABLE and runtime and runtime.market_gate.state == "allow")
        reason_codes = tuple(plan.decision.reason_codes) + (() if tradeable else (("runtime_pending",) if runtime is None else tuple(runtime.data_quality.reason_codes)))
        decision = PublicationDecision(plan_status=plan.decision.status, execution_status=execution_status, tradeable_now=tradeable, reason_codes=reason_codes)
        lineage = PublicationLineage(plan_id=plan.plan_id, runtime_id=runtime.runtime_id if runtime else None, producer_revision=plan.producer.revision, source_digest=plan.producer.source_digest)
        identity = json.dumps({"plan_id": plan.plan_id, "runtime_id": runtime.runtime_id if runtime else None, "decision": decision.model_dump(mode="json"), "lineage": lineage.model_dump(mode="json")}, sort_keys=True, separators=(",", ":"))
        publication = RecommendationPublication(publication_id=content_id("publication", identity), plan_id=plan.plan_id, runtime_id=runtime.runtime_id if runtime else None, published_at=published_at, decision=decision, candidates=plan.evaluated_candidates, lineage=lineage)
        return self.store.commit_publication(
            publication,
            expected_current_publication_id=(
                current.publication_id if current else None
            ) if expected_current_publication_id is ... else expected_current_publication_id,
        )
