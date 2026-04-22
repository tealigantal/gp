from __future__ import annotations

from typing import Dict, List

from ..contracts.objects import SideResult, BoardEntry
from ..runtime.utils import gen_id, now_iso


def detect_side_results(old_map: Dict[str, str], board: List[BoardEntry]) -> List[SideResult]:
    out: List[SideResult] = []
    for entry in board:
        prev = old_map.get(entry.symbol)
        now = entry.execution_state
        if prev and prev != now:
            out.append(SideResult(
                event_id=gen_id('side'),
                created_at=now_iso(),
                symbol=entry.symbol,
                kind='execution_state_change',
                title=f'{entry.symbol} 状态变化',
                body=f'{prev} -> {now}',
                refs={'symbol': entry.symbol, 'from': prev, 'to': now},
            ))
    return out
