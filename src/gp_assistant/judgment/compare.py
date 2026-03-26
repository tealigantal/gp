from __future__ import annotations

from typing import List

from ..contracts.objects import BoardEntry, Claim, Judgment
from ..runtime.utils import gen_id, now_iso


def compare_entries(session_id: str, entries: List[BoardEntry]) -> Judgment:
    ordered = sorted(entries, key=lambda e: (0 if e.can_open else 1, 1 if e.invalidated else 0, -e.live_score))
    winner = ordered[0] if ordered else None
    if not ordered:
        summary = '当前没有可比较的对象。'
        claims = []
    else:
        summary = f'{winner.symbol} 当前优先级更高；比较主要由 execution_state、live_score 与拉伸状态决定。'
        claims = [Claim(
            claim_id=gen_id('claim'),
            session_id=session_id,
            subject_type='compare_set',
            subject_id='|'.join(e.symbol for e in ordered),
            predicate='winner',
            value={'winner_symbol': winner.symbol, 'ranking': [e.symbol for e in ordered]},
            evidence_refs=[e.symbol for e in ordered],
            turn_id='pending',
            created_at=now_iso(),
        )]
    return Judgment(kind='compare', summary=summary, compare_entries=ordered, claims=claims, evidence_refs=[e.symbol for e in ordered])
