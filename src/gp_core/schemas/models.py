from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl, validator


class UserProfile(BaseModel):
    risk_level: str = Field(..., description="conservative|neutral|aggressive")
    style_preference: Optional[str] = Field(None, description="trend|range|high_vol|low_vol")
    universe: str = Field("A股")
    max_positions: int = Field(ge=1, default=3)
    sector_preference: List[str] = Field(default_factory=list)
    max_drawdown_tolerance: Optional[float] = None
    topk: int = Field(ge=1, default=3)


class MarketSource(BaseModel):
    provider: str
    url: Optional[str] = None
    title: Optional[str] = None
    snippet: Optional[str] = None
    fetched_at: Optional[str] = None  # ISO
    published_at: Optional[str] = None  # ISO if available
    article_summary: Optional[str] = None


class MarketContext(BaseModel):
    provider: str
    date_range: Dict[str, str]
    index_summary: Dict[str, Any] = Field(default_factory=dict)
    sector_rotation: List[Dict[str, Any]] = Field(default_factory=list)
    major_events: List[Dict[str, Any]] = Field(default_factory=list)
    market_style_guess: Dict[str, Any] = Field(default_factory=dict)
    risk_flags: List[str] = Field(default_factory=list)
    sources: List[MarketSource] = Field(default_factory=list)


class StrategySpec(BaseModel):
    id: str
    name: str
    tags: List[str]
    risk_profile: List[str]
    params: Dict[str, Any] = Field(default_factory=dict)


class StrategySelection(BaseModel):
    selected: List[Dict[str, Any]]
    rationale: str


class StrategyRunMetrics(BaseModel):
    win_rate: float = 0.0
    avg_return: float = 0.0
    max_drawdown: float = 0.0
    turnover: float = 0.0
    sample_period: Dict[str, str] = Field(default_factory=dict)


class StrategyRunResult(BaseModel):
    provider: str
    strategy_id: str
    name: str
    tags: List[str] = Field(default_factory=list)
    period: Dict[str, str]
    metrics: StrategyRunMetrics
    rules_summary: str
    signals: List[str] = Field(default_factory=list)
    suggestions: Dict[str, Any] = Field(default_factory=dict)  # entry/stop/take/position
    llm_explanation: str
    picks: List[Dict[str, Any]] = Field(default_factory=list)


class ChampionDecision(BaseModel):
    strategy_id: str
    name: str
    reason: str


class RecommendationItem(BaseModel):
    code: str
    name: Optional[str] = None
    direction: str = "long"
    thesis: str
    entry: Optional[str] = None
    stop_loss: Optional[str] = None
    take_profit: Optional[str] = None
    position_sizing: Optional[str] = None


class RecommendationResponse(BaseModel):
    provider: str
    summary: str
    chosen_strategy: Dict[str, Any]
    recommendations: List[RecommendationItem]
    risks: List[str]
    assumptions: List[str]
    evidence: List[str] = Field(default_factory=list)


class PipelineRunIndex(BaseModel):
    run_id: str
    end_date: str
    created_at: str
    artifacts: Dict[str, str]

