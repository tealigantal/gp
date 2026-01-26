from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import Strategy, OrderIntent


@dataclass
class TimeEntryParams:
    entry_time: str = "10:00:00"  # bar close time to confirm
    exit_time: str = "10:00:00"   # next-day fixed exit time
    pick_rank: int = 1            # 1-based rank in candidate list
    top_k: int = 1
    max_positions: int = 1
    stop_loss_pct: float = 0.0    # e.g., 0.03 (effective from next day)
    take_profit_pct: float = 0.0  # e.g., 0.05 (effective from next day)
    per_stock_cash: float = 0.25


class TimeEntryMin5(Strategy):
    requires_minutes = True

    def __init__(self, params: Optional[TimeEntryParams] = None):
        self.params = params or TimeEntryParams()
        self._bought_today: set[str] = set()

    def on_day_start(self, date: str, candidate_list: list[str], context: dict) -> None:
        self._bought_today.clear()
        context['candidates'] = candidate_list
        context['today'] = date

    def on_bar(self, bar: dict, context: dict) -> Optional[OrderIntent]:
        # Only consider the picked rank symbol(s)
        ts_code = bar['ts_code']
        cands = context.get('candidates', [])
        rank_idx = max(0, self.params.pick_rank - 1)
        allowed = set(cands[: max(self.params.top_k, self.params.pick_rank)])
        if ts_code not in allowed:
            return None
        t = bar['trade_time']
        hhmmss = t.split(' ')[1] if ' ' in t else t[-8:]
        if hhmmss == self.params.entry_time and ts_code not in self._bought_today:
            self._bought_today.add(ts_code)
            return OrderIntent('buy', ts_code, 0, 'TIME_ENTRY')
        return None

