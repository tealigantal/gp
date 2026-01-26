from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import Strategy, OrderIntent


@dataclass
class ORBParams:
    range_end_time: str = "10:00:00"
    breakout_bps: int = 0  # e.g., 10 bps
    vol_mult: float = 1.0  # require bar_vol >= vol_mult * avg_vol(range)
    exit_time: str = "10:00:00"  # next day fixed exit
    pick_rank: int = 1
    top_k: int = 1
    max_positions: int = 1
    stop_loss_pct: float = 0.0  # from next day
    per_stock_cash: float = 0.25


class OpenRangeBreakout(Strategy):
    requires_minutes = True

    def __init__(self, params: Optional[ORBParams] = None):
        self.params = params or ORBParams()
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
        st = self._state.setdefault(date, {}).setdefault(ts, {
            'range_high': None,
            'range_low': None,
            'range_vols': [],
            'armed': False,
            'bought': False,
        })
        # Build opening range
        if hhmmss <= self.params.range_end_time:
            st['range_high'] = float(bar['high']) if st['range_high'] is None else max(st['range_high'], float(bar['high']))
            st['range_low'] = float(bar['low']) if st['range_low'] is None else min(st['range_low'], float(bar['low']))
            st['range_vols'].append(float(bar.get('vol', 0)))
            return None
        # After range window, check breakout at bar close
        if st['bought']:
            return None
        cands = context.get('candidates', [])
        allowed = set(cands[: max(self.params.top_k, self.params.pick_rank)])
        if ts not in allowed:
            return None
        if st['range_high'] is None or st['range_low'] is None or not st['range_vols']:
            return None
        avg_vol = sum(st['range_vols']) / max(1, len(st['range_vols']))
        cond_px = st['range_high'] * (1 + self.params.breakout_bps / 10000.0)
        if float(bar['close']) >= cond_px and float(bar.get('vol', 0)) >= self.params.vol_mult * avg_vol:
            st['bought'] = True
            return OrderIntent('buy', ts, 0, 'ORB_BREAKOUT')
        return None

