from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ---------- Core Schemas ----------


@dataclass
class MarketSource:
    provider: str
    url: Optional[str] = None
    title: Optional[str] = None
    snippet: Optional[str] = None
    fetched_at: Optional[str] = None  # ISO datetime
    score: Optional[float] = None


@dataclass
class MarketContext:
    provider: str
    date_range: Dict[str, str]  # {start: YYYYMMDD, end: YYYYMMDD}
    index_summary: Dict[str, Any] = field(default_factory=dict)
    sector_rotation: List[Dict[str, Any]] = field(default_factory=list)
    major_events: List[Dict[str, Any]] = field(default_factory=list)
    market_style_guess: Dict[str, Any] = field(default_factory=dict)  # {style, reason}
    risk_flags: List[str] = field(default_factory=list)
    sources: List[MarketSource] = field(default_factory=list)
    cache_key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Convert nested dataclasses
        d["sources"] = [asdict(s) for s in self.sources]
        return d


@dataclass
class UserProfile:
    risk_level: str = "neutral"  # conservative | neutral | aggressive
    style_preference: Optional[str] = None  # trend | range | high_vol | low_vol
    universe: str = "A股"
    max_positions: int = 3
    sector_preference: List[str] = field(default_factory=list)
    max_drawdown_tolerance: Optional[float] = None
    topk: int = 3


@dataclass
class StrategyRunResult:
    provider: str  # llm | rule | mock
    strategy_id: str
    name: str
    tags: List[str]
    period: Dict[str, str]  # {start, end}
    metrics: Dict[str, float]  # {win_rate, avg_return, max_drawdown, turnover, sharpe?}
    notes: Optional[str] = None
    picks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SelectedStrategy:
    strategy_id: str
    reason: str
    tags: List[str] = field(default_factory=list)


@dataclass
class StrategySelection:
    selected: List[SelectedStrategy]
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return {"selected": [asdict(x) for x in self.selected], "rationale": self.rationale}


@dataclass
class RecommendationItem:
    code: str
    name: Optional[str] = None
    direction: str = "long"  # long | short
    thesis: str = ""
    entry: Optional[str] = None
    stop_loss: Optional[str] = None
    take_profit: Optional[str] = None
    position_sizing: Optional[str] = None


@dataclass
class RecommendationResponse:
    provider: str  # llm | fallback | mock
    summary: str
    chosen_strategy: Dict[str, Any]
    recommendations: List[RecommendationItem]
    risks: List[str]
    assumptions: List[str]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["recommendations"] = [asdict(x) for x in self.recommendations]
        return d


# ---------- Helpers ----------


def save_json(path, obj: Dict[str, Any]) -> None:
    import json
    p = path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

