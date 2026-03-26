from __future__ import annotations

from typing import List

from ..contracts.objects import Claim, Judgment, MarketBook
from ..runtime.utils import gen_id, now_iso
from .publish import publish_run


def make_recommendation(session_id: str, book: MarketBook, topk: int = 3) -> Judgment:
    run = publish_run(session_id=session_id, book=book, topk=topk)
    claims: List[Claim] = []
    for entry in run.picks:
        claims.append(Claim(
            claim_id=gen_id('claim'),
            session_id=session_id,
            subject_type='symbol',
            subject_id=entry.symbol,
            predicate='rank',
            value={'rank': entry.rank, 'style_label': entry.style_label, 'execution_state': entry.execution_state},
            evidence_refs=[run.run_id, book.book_version],
            turn_id='pending',
            created_at=now_iso(),
        ))
    summary = '已基于当前账本发布一轮推荐。' if run.tradeable else f'当前更偏观察：{run.reason or "账本不支持主动建仓"}'
    return Judgment(
        kind='recommend',
        summary=summary,
        run=run,
        compare_entries=run.picks,
        claims=claims,
        evidence_refs=[book.book_version, run.run_id],
    )
