from __future__ import annotations

from ..contracts.objects import Judgment


def judge_chat() -> Judgment:
    return Judgment(
        kind='chat',
        summary='non_trading_chat',
        evidence_refs=[],
    )

