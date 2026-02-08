from __future__ import annotations

from typing import Any, List, Dict, Optional
from dataclasses import dataclass

from ..core.types import ToolResult
from .universe import UniverseResult


def run_rank(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    """Rank candidates using a simple heuristic (placeholder)."""
    candidates: List[Dict] = args.get("candidates") or []
    return ToolResult(ok=True, message=f"排名完成: {len(candidates)} 条", data={"ranked": candidates})


@dataclass
class BacktestSummary:
    k: int
    win_rate_5: float
    avg_return_5: float
    mdd10_avg: float
    sample_warning: bool


@dataclass
class PickItem:
    symbol: str
    name: Optional[str]
    sector: Optional[str]
    indicators: Dict[str, float]
    noise_level: str
    strategy_attribution: List[str]
    backtest: BacktestSummary
    risk_constraints: Dict[str, Any]
    actions: Dict[str, str]
    time_stop: str
    events: Dict[str, Any]
    score: float


@dataclass
class PickResult:
    top: List[PickItem]
    kept_count: int
    watch_count: int
    rejected_count: int


def _noise_level(atr_pct: float, bbwidth: float) -> str:
    if atr_pct < 0.02 and bbwidth < 0.05:
        return "Q0"
    if atr_pct < 0.04 and bbwidth < 0.1:
        return "Q1"
    if atr_pct < 0.06 and bbwidth < 0.15:
        return "Q2"
    return "Q3"


def rank_candidates(
    universe_result: UniverseResult,
    features_by_symbol: Dict[str, Any],  # df_feat per symbol
    backtest_stats_by_symbol: Dict[str, Any],
    champion_state: Dict[str, Any] | None,
    config=None,
) -> PickResult:
    items: List[PickItem] = []

    def get(df, col):
        try:
            v = float(df[col].iloc[-1])
            return v
        except Exception:
            return float("nan")

    # consider both kept and watch-only (flag carried in reasons)
    for entry in list(universe_result.kept) + list(universe_result.watch_only):
        sym = entry.symbol
        df = features_by_symbol.get(sym)
        bt = backtest_stats_by_symbol.get(sym)
        if df is None or bt is None:
            continue
        inds = {
            "amount_5d_avg": get(df, "amount_5d_avg"),
            "atr_pct": get(df, "atr_pct"),
            "ma20": get(df, "ma20"),
            "ma60": get(df, "ma60"),
            "bias6": get(df, "bias6"),
            "rsi2": get(df, "rsi2"),
            "bbwidth20": get(df, "bbwidth20"),
        }
        noise = _noise_level(inds.get("atr_pct") or 0.0, inds.get("bbwidth20") or 0.0)
        strat_attr: List[str] = []
        if bool(df.get("bias6_cross_up", [False])[-1:][0]):
            strat_attr.append("bias6_cross_up")

        wr5 = float(getattr(bt, "win_rate_5", 0.0))
        ar5 = float(getattr(bt, "avg_return_5", 0.0))
        risk_penalty = (inds.get("atr_pct") or 0.0) * 2 + (inds.get("bbwidth20") or 0.0)
        sample_penalty = 0.5 if getattr(bt, "sample_warning", False) else 0.0
        score = max(0.0, wr5 * 1.5 + ar5 - risk_penalty - sample_penalty)

        item = PickItem(
            symbol=sym,
            name=entry.name,
            sector=None,
            indicators=inds,
            noise_level=noise,
            strategy_attribution=strat_attr,
            backtest=BacktestSummary(
                k=int(getattr(bt, "k", 0)),
                win_rate_5=wr5,
                avg_return_5=ar5,
                mdd10_avg=float(getattr(bt, "mdd10_avg", 0.0)),
                sample_warning=bool(getattr(bt, "sample_warning", False)),
            ),
            risk_constraints={
                "universe_reasons": entry.reason_codes or ["PASS"],
                "facts": entry.facts,
            },
            actions={
                "morning": "早盘：缩量回踩中轨不破并回收；",
                "afternoon": "午后：放量转强收盘确认，避免追高冲动。",
            },
            time_stop="第3天收盘未走强则退出，控制单票风险。",
            events={
                "announcements": "未接入公告源，默认中性（降级）。",
                "theme": "未接入主题主线源，默认中性（降级）。",
            },
            score=score,
        )
        items.append(item)

    items.sort(key=lambda x: x.score, reverse=True)
    top = items[:10]
    return PickResult(
        top=top,
        kept_count=len(universe_result.kept),
        watch_count=len(universe_result.watch_only),
        rejected_count=len(universe_result.rejected),
    )
