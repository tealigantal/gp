from __future__ import annotations

from typing import Dict, Iterable, List

from .base import OrderIntent, Strategy


class BreakoutStrategy(Strategy):
    """Simple 20-bar breakout: if price crosses above prev 20-high at bar close, buy."""

    def on_bar(self, trade_time: str, bar_slice) -> List[OrderIntent]:
        signals: List[OrderIntent] = []
        lookback = int(self.params.get("lookback", 20))
        lot = int(self.params.get("lot_shares", 100))
        for ts, hist in bar_slice.get("history", {}).items():
            # hist is list of dicts sorted by time for this symbol (prev bars including current closed bar)
            if len(hist) < lookback + 1:
                continue
            prev = hist[-(lookback + 1) : -1]
            cur = hist[-1]
            prev_high = max(b["high"] for b in prev)
            if cur["close"] > prev_high:
                signals.append(OrderIntent(ts, "BUY", lot, reason="breakout"))
        return signals

