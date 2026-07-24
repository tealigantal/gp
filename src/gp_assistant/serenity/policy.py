from __future__ import annotations

from ..contracts.evidence import SerenityDecisionBinding


MAX_ADDITIVE_WEIGHT = 0.03


def bind(*, reference_id: str | None, policy_revision: str, requested_weight: float, causal_ready: bool, reason_codes: tuple[str, ...] = ()) -> SerenityDecisionBinding:
    weight = min(MAX_ADDITIVE_WEIGHT, max(0.0, requested_weight)) if causal_ready else 0.0
    degraded_reasons = reason_codes if "serenity_batch_unavailable" in reason_codes else (*reason_codes, "serenity_batch_unavailable")
    return SerenityDecisionBinding(reference_id=reference_id, policy_revision=policy_revision, applied_weight=weight, state="active" if weight else "degraded", reason_codes=reason_codes if causal_ready else degraded_reasons)
