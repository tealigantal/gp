from __future__ import annotations

from ..contracts.objects import Claim, Judgment, BoardEntry
from ..runtime.utils import gen_id, now_iso


def judge_followup(session_id: str, entry: BoardEntry) -> Judgment:
    if entry.invalidated:
        summary = f'{entry.symbol} 当前已进入失效暂不入场，不适合继续按原计划开仓。'
    elif entry.execution_state == 'extended':
        summary = f'{entry.symbol} 当前已有拉伸，仍可跟踪，但赔率明显下降。'
    elif entry.execution_state == 'actionable':
        summary = f'{entry.symbol} 当前仍在可执行区，但仍需按止损与仓位约束执行。'
    else:
        summary = f'{entry.symbol} 当前更适合暂不入场，等待更优执行状态。'
    claims = [Claim(
        claim_id=gen_id('claim'),
        session_id=session_id,
        subject_type='symbol',
        subject_id=entry.symbol,
        predicate='execution_state',
        value={'state': entry.execution_state, 'can_open': entry.can_open, 'invalidated': entry.invalidated},
        evidence_refs=[entry.symbol],
        turn_id='pending',
        created_at=now_iso(),
    )]
    return Judgment(kind='followup', summary=summary, subject_entry=entry, claims=claims, evidence_refs=[entry.symbol])
