from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass
class ServiceRiskConfig:
    max_positions: int = 10
    per_symbol_max_fraction: float = 0.2
    cooldown_days: int = 0


def limit_picks(picks: List[str], cfg: ServiceRiskConfig) -> List[str]:
    # trivial enforcement: cap count
    return picks[: max(0, int(cfg.max_positions))]

