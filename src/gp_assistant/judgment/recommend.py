from __future__ import annotations

from typing import List

from ..contracts.objects import Claim, Judgment, MarketBook
from ..runtime.utils import gen_id, now_iso
from .publish import publish_run


def make_recommendation(session_id: str, book: MarketBook, topk: int = 3) -> Judgment:
    run = publish_run(session_id=session_id, book=book, topk=topk)
    claims: List[Claim] = []
    for entry in run.picks:
        claims.append(
            Claim(
                claim_id=gen_id("claim"),
                session_id=session_id,
                subject_type="symbol",
                subject_id=entry.symbol,
                predicate="rank",
                value={
                    "rank": entry.rank,
                    "style_label": entry.style_label,
                    "execution_state": entry.execution_state,
                    "recommendation_state": entry.recommendation_state,
                    "signal_type": entry.signal_type,
                    "probability": getattr(entry.pick, "probability", {}),
                    "ranking": getattr(entry.pick, "ranking", {}),
                    "decision_context_snapshot_id": getattr(entry.pick, "decision_context_snapshot_id", None),
                },
                evidence_refs=[run.run_id, book.book_version],
                turn_id="pending",
                created_at=now_iso(),
            )
        )

    if run.slot_status and run.slot_status != "OK":
        summary = f"当前 slot 状态为 {run.slot_status}，数据受限，当前只保留日线级建议。"
    elif run.tradeable:
        summary = "已基于当前统一 artifact 生成本轮推荐。"
    else:
        summary = f"当前更偏暂不入场，原因：{run.reason or '当前闸门未放行'}"

    return Judgment(
        kind="recommend",
        summary=summary,
        run=run,
        compare_entries=run.picks,
        claims=claims,
        evidence_refs=[book.book_version, run.run_id],
    )
