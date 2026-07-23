from __future__ import annotations

from ..contracts.catalog import CandidateDisposition
from ..contracts.decision import CandidateDecision


class AdaptiveDecisionEngine:
    """The sole selector: it consumes fixed evidence and never accepts LLM output."""

    def select(self, candidates: tuple[CandidateDecision, ...], *, maximum_selected: int = 3) -> tuple[CandidateDecision, ...]:
        ordered = sorted(candidates, key=lambda item: (-item.adaptive_score, item.symbol))
        selected = 0
        result: list[CandidateDecision] = []
        for position, candidate in enumerate(ordered, start=1):
            if candidate.adaptive_score >= 0.5 and selected < maximum_selected:
                disposition = CandidateDisposition.SELECTED
                selected += 1
            elif candidate.adaptive_score >= 0.4:
                disposition = CandidateDisposition.RESERVE
            else:
                disposition = CandidateDisposition.REJECTED
            result.append(candidate.model_copy(update={"disposition": disposition, "ranking": candidate.ranking.model_copy(update={"rank": position})}))
        return tuple(result)
