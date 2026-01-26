from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import Strategy, OrderIntent


@dataclass
class BaselineParams:
    buy_time: str = "09:45:00"
    sell_time: str = "10:00:00"
    buy_top_k: int = 1
    per_stock_cash: float = 0.25


class BaselineStrategy(Strategy):
    def __init__(self, params: Optional[BaselineParams] = None):
        self.params = params or BaselineParams()
        self._today_bought: set[str] = set()

    def on_day_start(self, date: str, candidate_list: list[str], context: dict) -> None:
        self._today_bought.clear()
        context.setdefault('pending_sell', {})
        context['today'] = date
        # Record planned sells for previous day buys — engine should enforce T+1

    def on_bar(self, bar: dict, context: dict) -> Optional[OrderIntent]:
        # bar: { 'trade_time': 'YYYY-MM-DD HH:MM:SS', 'ts_code': ..., 'open': ..., ... }
        t = bar.get('trade_time', '')
        hhmmss = t.split(' ')[1] if ' ' in t else t[-8:]
        ts_code = bar.get('ts_code')

        # Sell at fixed time next day is handled by engine via context['pending_sell']
        # Here only demonstrate buy logic for top K codes
        if hhmmss == self.params.buy_time:
            # context should provide today's candidate list
            cands = context.get('candidates', [])[: self.params.buy_top_k]
            if ts_code in cands and ts_code not in self._today_bought:
                # target shares left for engine to compute by per_stock_cash
                return OrderIntent(side='buy', ts_code=ts_code, target_shares=0, reason='baseline_buy')
        return None

    def on_day_end(self, date: str, context: dict) -> None:
        pass

