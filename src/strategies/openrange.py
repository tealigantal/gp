from __future__ import annotations

from typing import List

from .base import OrderIntent, Strategy


class OpenRangeStrategy(Strategy):
    """Open range breakout: after first N bars, buy break above range high."""

    def on_bar(self, trade_time: str, bar_slice) -> List[OrderIntent]:
        signals: List[OrderIntent] = []
        n = int(self.params.get("range_bars", 3))
        lot = int(self.params.get("lot_shares", 100))
        for ts, hist in bar_slice.get("history", {}).items():
            if len(hist) < n + 1:
                continue
            first_n = hist[:n]
            cur = hist[-1]
            rng_high = max(b["high"] for b in first_n)
            if cur["close"] > rng_high:
                signals.append(OrderIntent(ts, "BUY", lot, reason="open_range_breakout"))
        return signals

