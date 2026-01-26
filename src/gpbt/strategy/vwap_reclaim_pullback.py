from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import Strategy, OrderIntent


@dataclass
class VWAPParams:
    start_time: str = "10:00:00"
    dip_bps: int = 0  # require price below vwap by at least dip_bps to arm
    exit_time: str = "10:00:00"
    pick_rank: int = 1
    top_k: int = 1
    max_positions: int = 1
    stop_loss_pct: float = 0.0
    per_stock_cash: float = 0.25


class VWAPReclaimPullback(Strategy):
    requires_minutes = True

    def __init__(self, params: Optional[VWAPParams] = None):
        self.params = params or VWAPParams()
        self._state = {}

    def on_day_start(self, date: str, candidate_list: list[str], context: dict) -> None:
        self._state[date] = {}
        context['candidates'] = candidate_list
        context['today'] = date

    def on_bar(self, bar: dict, context: dict):
        ts = bar['ts_code']
        t = bar['trade_time']
        hhmmss = t.split(' ')[1] if ' ' in t else t[-8:]
        date = context['today']
        s = self._state.setdefault(date, {}).setdefault(ts, {
            'sum_pv': 0.0,
            'sum_v': 0.0,
            'armed': False,
            'bought': False,
        })
        price = float(bar['close'])
        vol = float(bar.get('vol', 0))
        typical = (float(bar['high']) + float(bar['low']) + float(bar['close'])) / 3.0
        s['sum_pv'] += typical * vol
        s['sum_v'] += vol
        vwap = (s['sum_pv'] / s['sum_v']) if s['sum_v'] > 0 else price

        if hhmmss < self.params.start_time or s['bought']:
            return None

        # Arm when below vwap by dip_bps
        if not s['armed']:
            if price <= vwap * (1 - self.params.dip_bps / 10000.0):
                s['armed'] = True
            return None

        # Reclaim when close crosses above vwap
        cands = context.get('candidates', [])
        allowed = set(cands[: max(self.params.top_k, self.params.pick_rank)])
        if ts not in allowed:
            return None
        if price >= vwap:
            s['bought'] = True
            return OrderIntent('buy', ts, 0, 'VWAP_RECLAIM')
        return None

