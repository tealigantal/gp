from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional


@dataclass
class OrderIntent:
    ts_code: str
    side: str  # "BUY" or "SELL"
    shares: int
    reason: str = ""


class Strategy:
    """Strategy interface.

    Implementations must only use current-bar-and-before data. The engine
    supplies data slices per bar and current candidate universe.
    """

    def __init__(self, name: str, params: Dict) -> None:
        self.name = name
        self.params = params

    # hooks
    def on_day_start(self, trade_date: str, universe: Iterable[str]) -> List[OrderIntent]:
        return []

    def on_bar(self, trade_time: str, bar_slice) -> List[OrderIntent]:
        # bar_slice is a dict: {ts_code: {open, high, low, close, vol, amount}}
        return []

    def on_day_end(self, trade_date: str) -> List[OrderIntent]:
        return []

