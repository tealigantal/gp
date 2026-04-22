from __future__ import annotations

from ..contracts.objects import BoardEntry, Judgment


def judge_exit(entry: BoardEntry, portfolio_slice: dict) -> Judgment:
    stop_price = entry.pick.stop_plan.get('price') or entry.pick.stop_plan.get('stop')
    take_price = entry.pick.take_profit_plan.get('price') or entry.pick.take_profit_plan.get('take')
    if entry.invalidated:
        action = 'exit'
        summary = f'{entry.symbol} 已触发失效观察，优先考虑退出或显著降低暴露。'
    elif entry.execution_state == 'extended':
        action = 'trim_or_hold'
        summary = f'{entry.symbol} 已拉伸，新增赔率不佳；若已有仓位，更偏向持有/分批减而非追价。'
    else:
        action = 'hold'
        summary = f'{entry.symbol} 原 thesis 尚未失效，当前更偏向按计划持有与跟踪。'
    return Judgment(
        kind='exit',
        summary=summary,
        subject_entry=entry,
        exit_view={'action': action, 'stop_price': stop_price, 'take_price': take_price, 'portfolio': portfolio_slice},
        evidence_refs=[entry.symbol],
    )
