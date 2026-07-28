from __future__ import annotations

from .catalog import PlanStatus
from .decision import RecommendationPlan


def publication_ineligibility(plan: RecommendationPlan) -> str | None:
    """Return the sole reason a plan may not replace ``current_publication``.

    This is intentionally shared by the service and the persistence boundary:
    no caller may turn a pending recovery artifact into a user-visible plan by
    bypassing ``PublicationService``.
    """
    if not plan.candidate_universe.complete:
        return "publication_plan_incomplete"
    if plan.daily_evidence is None or plan.daily_evidence_date is None:
        return "publication_daily_evidence_missing"
    if plan.decision.status not in {PlanStatus.RECOMMEND, PlanStatus.NO_RECOMMEND}:
        return "publication_plan_not_ready"
    if "daily_evidence_pending" in plan.decision.reason_codes:
        return "publication_plan_not_ready"
    return None


def require_publication_eligible(plan: RecommendationPlan) -> None:
    reason = publication_ineligibility(plan)
    if reason is not None:
        raise ValueError(reason)
