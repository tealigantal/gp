from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Prefilter:
    min_turnover: Optional[float] = None
    max_gap_pct: Optional[float] = 2.0
    avoid_near_resistance: bool = True


@dataclass
class Setup:
    name: str
    params: Dict[str, float] = field(default_factory=dict)


@dataclass
class Confirmation:
    min_signals_q0: int = 1
    min_signals_q2: int = 2


@dataclass
class EntryPlan:
    description: str  # structure-only, no price triggers


@dataclass
class ExitRules:
    time_stop_days: int = 3
    invalidate_on_gap_pct: float = 2.0


@dataclass
class PositionRules:
    lot_size: int = 100
    risk_budget_pct: float = 0.008  # 0.8%


@dataclass
class StrategyDSL:
    id: str
    name: str
    family: str
    market_env_allowed: List[str]
    prefilters: Prefilter
    setup_conditions: Setup
    confirmation_rules: Confirmation
    entry_plan: EntryPlan
    exit_rules: ExitRules
    position_rules: PositionRules
    invalidation_rules: Dict[str, float] = field(default_factory=dict)


def s1_rsi2_pullback() -> StrategyDSL:
    return StrategyDSL(
        id="S1",
        name="RSI2 Pullback",
        family="A",
        market_env_allowed=["A", "B", "C"],
        prefilters=Prefilter(min_turnover=None, max_gap_pct=2.0, avoid_near_resistance=True),
        setup_conditions=Setup(name="MA20_up_or_flat_and_pullback", params={"rsi2_max": 15.0, "bias6_min": -6.0}),
        confirmation_rules=Confirmation(min_signals_q0=1, min_signals_q2=2),
        entry_plan=EntryPlan(description="日线结构满足且盘中承接改善（量比回升、弱转强），不以价格触发为依据。"),
        exit_rules=ExitRules(time_stop_days=3, invalidate_on_gap_pct=2.0),
        position_rules=PositionRules(lot_size=100, risk_budget_pct=0.008),
        invalidation_rules={"near_pressure": 1.0},
    )

