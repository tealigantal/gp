from __future__ import annotations

from datetime import datetime
import json

from ..contracts.catalog import PlanStatus
from ..contracts.decision import PlanCommitCommand, PlanDecision, PlanLookupKey, RecommendationPlan
from ..contracts.evidence import CandidateUniverseBinding, DailyEvidenceBinding, DecisionPolicyBinding, ProducerIdentity, SerenityDecisionBinding
from ..contracts.ids import content_id
from ..contracts.market import ResolvedPlanTarget
from ..decision_engine.adaptive import AdaptiveDecisionEngine
from ..store import ContractStore


class PlanService:
    def __init__(self, store: ContractStore):
        self.store = store

    def get_or_create(
        self,
        *,
        target: ResolvedPlanTarget,
        universe: CandidateUniverseBinding,
        policy: DecisionPolicyBinding,
        producer: ProducerIdentity,
        evaluated_candidates: tuple,
        serenity: SerenityDecisionBinding,
        generated_at: datetime,
    ) -> PlanCommitCommand:
        key = PlanLookupKey(
            market=target.market,
            market_session_date=target.market_session_date,
            daily_evidence_date=target.daily_evidence_date,
            candidate_universe_id=universe.candidate_universe_id,
            candidate_universe_content_digest=universe.content_digest,
            decision_policy_revision=policy.revision,
            adaptive_policy_state_version=policy.adaptive_policy_state_version,
            producer_revision=producer.revision,
            producer_source_digest=producer.source_digest,
            selection_policy=policy.selection_policy,
            risk_profile=policy.risk_profile,
        )
        existing = self.store.load_exact_plan(__import__("hashlib").sha256(json.dumps(key.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest())
        if existing:
            return PlanCommitCommand(plan=existing, serenity_reference=None, evidence_writes=())
        evaluated_candidates = AdaptiveDecisionEngine().select(tuple(evaluated_candidates))
        status = PlanStatus.RECOMMEND if target.state.value == "ready" and universe.complete and any(item.disposition.value == "selected" for item in evaluated_candidates) else PlanStatus.NO_RECOMMEND if target.state.value == "ready" and universe.complete else PlanStatus.UNAVAILABLE
        reasons = () if status is PlanStatus.RECOMMEND else (("daily_evidence_pending",) if target.state.value != "ready" else ("candidate_universe_incomplete",) if not universe.complete else ("no_selected_candidate",))
        decision = PlanDecision(status=status, reason_codes=reasons)
        plan_id = content_id("plan", json.dumps({"key": key.model_dump(mode="json"), "decision": decision.model_dump(mode="json"), "candidates": [item.model_dump(mode="json") for item in evaluated_candidates], "serenity": serenity.model_dump(mode="json")}, sort_keys=True, separators=(",", ":")))
        evidence = DailyEvidenceBinding(market=target.market, daily_evidence_date=target.daily_evidence_date, source=universe.source, content_digest=universe.content_digest) if target.daily_evidence_date else None
        plan = RecommendationPlan(plan_id=plan_id, lookup_key=key, market=target.market, market_session_date=target.market_session_date, daily_evidence_date=target.daily_evidence_date, generated_at=generated_at, decision=decision, candidate_universe=universe, daily_evidence=evidence, decision_policy=policy, producer=producer, evaluated_candidates=tuple(evaluated_candidates), serenity=serenity)
        self.store.commit_plan(plan)
        return PlanCommitCommand(plan=plan, serenity_reference=None, evidence_writes=())
