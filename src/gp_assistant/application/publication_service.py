from __future__ import annotations

import json

from ..contracts.catalog import ExecutionStatus
from ..contracts.ids import content_id
from ..contracts.publication import PublicationDecision, PublicationLineage, RecommendationPublication
from ..store import ContractStore


class PublicationService:
    def __init__(self, store: ContractStore):
        self.store = store

    def publish(self, *, plan_id: str, runtime_id: str | None, published_at) -> RecommendationPublication:
        plan = self.store.load_plan(plan_id)
        if plan is None:
            raise ValueError("plan_not_found")
        runtime = self.store.load_runtime(runtime_id) if runtime_id else None
        if runtime_id and runtime is None:
            raise ValueError("runtime_plan_mismatch")
        if runtime and runtime.plan_id != plan.plan_id:
            raise ValueError("runtime_plan_mismatch")
        if runtime and runtime.market_session_date != plan.market_session_date:
            raise ValueError("runtime_session_mismatch")
        execution_status = ExecutionStatus.AVAILABLE if runtime and runtime.data_quality.state.value == "ready" else ExecutionStatus.PENDING if runtime is None else ExecutionStatus.UNAVAILABLE
        tradeable = bool(plan.decision.status.value == "recommend" and execution_status is ExecutionStatus.AVAILABLE and runtime and runtime.market_gate.state == "allow")
        reason_codes = tuple(plan.decision.reason_codes) + (() if tradeable else (("runtime_pending",) if runtime is None else tuple(runtime.data_quality.reason_codes)))
        decision = PublicationDecision(plan_status=plan.decision.status, execution_status=execution_status, tradeable_now=tradeable, reason_codes=reason_codes)
        lineage = PublicationLineage(plan_id=plan.plan_id, runtime_id=runtime.runtime_id if runtime else None, producer_revision=plan.producer.revision, source_digest=plan.producer.source_digest)
        identity = json.dumps({"plan_id": plan.plan_id, "runtime_id": runtime.runtime_id if runtime else None, "decision": decision.model_dump(mode="json"), "lineage": lineage.model_dump(mode="json")}, sort_keys=True, separators=(",", ":"))
        publication = RecommendationPublication(publication_id=content_id("publication", identity), plan_id=plan.plan_id, runtime_id=runtime.runtime_id if runtime else None, published_at=published_at, decision=decision, candidates=plan.evaluated_candidates, lineage=lineage)
        self.store.commit_publication(publication)
        return publication
