from __future__ import annotations

from ..contracts.evidence import SerenityDecisionBinding


MAX_ADDITIVE_WEIGHT = 0.08


def bind(*, reference_id: str | None, policy_revision: str, requested_weight: float, causal_ready: bool, reason_codes: tuple[str, ...] = ()) -> SerenityDecisionBinding:
    weight = min(MAX_ADDITIVE_WEIGHT, max(0.0, requested_weight)) if causal_ready else 0.0
    return SerenityDecisionBinding(reference_id=reference_id, policy_revision=policy_revision, applied_weight=weight, state="active" if weight else "shadow", reason_codes=reason_codes if causal_ready else (*reason_codes, "causal_gate_not_ready"))
