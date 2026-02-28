from __future__ import annotations

from typing import Dict, Iterable, List

from .base import OrderIntent, Strategy


class BaselineStrategy(Strategy):
    """Baseline: buy TopK at fixed time; sell next day close (engine enforces T+1)."""

    def on_day_start(self, trade_date: str, universe: Iterable[str]) -> List[OrderIntent]:
        # Baseline defers buys to a fixed intraday time defined in params.
        return []

    def on_bar(self, trade_time: str, bar_slice) -> List[OrderIntent]:
        # If time matches entry_time, buy topK from universe hint inside bar_slice
        entry_time = self.params.get("entry_time", "09:50:00")
        universe: List[str] = bar_slice.get("universe", [])
        if trade_time.endswith(entry_time):
            topk = int(self.params.get("topk", 1))
            picks = universe[:topk]
            shares = int(self.params.get("lot_shares", 100))
            return [OrderIntent(ts, "BUY", shares, reason="baseline_entry") for ts in picks]
        return []

    def on_day_end(self, trade_date: str) -> List[OrderIntent]:
        if self.params.get("exit_next_day_close", True):
            # Engine handles scheduling; here we signal intent to exit all at day end
            return [OrderIntent("__ALL__", "SELL", 0, reason="baseline_exit_next_day_close")]
        return []

