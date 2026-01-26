from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class OrderIntent:
    side: str  # 'buy' | 'sell'
    ts_code: str
    target_shares: int
    reason: str


class Strategy:
    # Override in subclasses
    requires_minutes: bool = True

    def on_day_start(self, date: str, candidate_list: list[str], context: dict) -> None:
        pass

    def on_bar(self, bar: dict, context: dict) -> Optional[OrderIntent]:
        return None

    def on_day_end(self, date: str, context: dict) -> None:
        pass
