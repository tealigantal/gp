from __future__ import annotations

from typing import Dict, List

from ..contracts.objects import AdvicePick, BoardEntry, DayBook, SymbolPulse


def _base_entry_summary(pick: AdvicePick, pulse: SymbolPulse | None) -> str:
    if pulse is None or pulse.last_bar_at is None:
        return f"{pick.symbol} 结构候选，等待盘中5分状态。"
    if pulse.invalidated:
        return f"{pick.symbol} 已触发失效观察，优先等待重新站稳。"
    if pulse.execution_state == 'extended':
        return f"{pick.symbol} 已有拉伸，赔率下降。"
    if pulse.execution_state == 'actionable':
        return f"{pick.symbol} 当前仍在可执行区。"
    return f"{pick.symbol} 当前更适合观察。"


def build_board(daybook: DayBook, pulse_map: Dict[str, SymbolPulse]) -> List[BoardEntry]:
    entries: List[BoardEntry] = []
    for idx, pick in enumerate(daybook.picks, start=1):
        p0 = pulse_map.get(pick.symbol)
        # If pulse is marked stale, treat as absent to avoid leaking yesterday's intraday state
        pulse = None if (p0 is not None and getattr(p0, 'is_stale', False)) else p0
        base = float(pick.scores.get('final') or 0.0)
        pulse_score = float(pulse.pulse_score if pulse else 0.0)
        invalidated = bool(pulse.invalidated) if pulse else False
        stretched = bool((pulse.execution_state == 'extended') if pulse else False)
        execution_state = pulse.execution_state if pulse else 'observe'
        can_open = bool(daybook.tradeable and not invalidated and execution_state == 'actionable')
        live_score = base + pulse_score - (0.3 if stretched else 0.0) - (1.0 if invalidated else 0.0)
        entries.append(BoardEntry(
            symbol=pick.symbol,
            name=pick.name,
            rank=idx,
            final_score=base,
            live_score=float(live_score),
            execution_state=execution_state,
            can_open=can_open,
            stretched=stretched,
            invalidated=invalidated,
            summary=_base_entry_summary(pick, pulse),
            style_label=pick.style_label,
            pick=pick,
            pulse=pulse,
        ))
    entries.sort(key=lambda e: (0 if e.can_open else 1, 1 if e.invalidated else 0, -e.live_score))
    for i, entry in enumerate(entries, start=1):
        entry.rank = i
        entry.pick.rank = i
    return entries
