from __future__ import annotations

from ..contracts.catalog import CandidateDisposition
from ..contracts.decision import CandidateDecision


class AdaptiveDecisionEngine:
    """The sole selector: it consumes fixed evidence and never accepts LLM output."""

    def select(
        self,
        candidates: tuple[CandidateDecision, ...],
        *,
        maximum_selected: int = 3,
        selection_eligible_symbols: frozenset[str] | None = None,
    ) -> tuple[CandidateDecision, ...]:
        if selection_eligible_symbols is None:
            ordered = sorted(candidates, key=lambda item: (-item.adaptive_score, item.symbol))
        else:
            eligible = sorted(
                (item for item in candidates if item.symbol in selection_eligible_symbols),
                key=lambda item: (-item.adaptive_score, item.symbol),
            )
            contextual = sorted(
                (item for item in candidates if item.symbol not in selection_eligible_symbols),
                key=lambda item: (-item.adaptive_score, item.symbol),
            )
            ordered = [*eligible, *contextual]
        selected = 0
        result: list[CandidateDecision] = []
        for position, candidate in enumerate(ordered, start=1):
            selection_eligible = selection_eligible_symbols is None or candidate.symbol in selection_eligible_symbols
            if selection_eligible and candidate.adaptive_score >= 0.5 and selected < maximum_selected:
                disposition = CandidateDisposition.SELECTED
                selected += 1
            elif candidate.adaptive_score >= 0.4:
                disposition = CandidateDisposition.RESERVE
            else:
                disposition = CandidateDisposition.REJECTED
            result.append(candidate.model_copy(update={"disposition": disposition, "ranking": candidate.ranking.model_copy(update={"rank": position})}))
        return tuple(result)
