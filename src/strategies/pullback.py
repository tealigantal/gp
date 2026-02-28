from __future__ import annotations

from typing import List

from .base import OrderIntent, Strategy


class PullbackStrategy(Strategy):
    """Buy on pullback to moving average reclaim."""

    def on_bar(self, trade_time: str, bar_slice) -> List[OrderIntent]:
        signals: List[OrderIntent] = []
        ma_win = int(self.params.get("ma_window", 20))
        lot = int(self.params.get("lot_shares", 100))
        for ts, hist in bar_slice.get("history", {}).items():
            if len(hist) < ma_win + 1:
                continue
            closes = [b["close"] for b in hist[-(ma_win + 1) : -1]]
            ma = sum(closes) / len(closes)
            cur = hist[-1]
            prev = hist[-2]
            # yesterday below MA, today reclaim above MA
            if prev["close"] < ma <= cur["close"]:
                signals.append(OrderIntent(ts, "BUY", lot, reason="pullback_reclaim"))
        return signals

