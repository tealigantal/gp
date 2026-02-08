# 简介：工具 - 排名/排序辅助（对候选或指标进行排序展示）。
from __future__ import annotations

from typing import Any, List, Dict, Optional
from dataclasses import dataclass

from ..core.types import ToolResult
from .universe import UniverseResult, build_universe, UniverseEntry
from .market_data import normalize_daily_ohlcv
from .signals import compute_indicators
from .backtest import StrategyDef, run_event_backtest
from ..providers.factory import get_provider


def run_rank(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    """对候选/默认池进行完整打分排序（非占位）。

    支持：
    - symbols: 可选，指定一组标的；缺省走默认 universe
    - topk: 返回前K条（默认10）
    - as_of: 可选日期（YYYY-MM-DD）
    """
    symbols: List[str] | None = args.get("symbols")
    topk: int = int(args.get("topk", 10) or 10)
    as_of = args.get("as_of")

    provider = get_provider()
    # Build universe
    if symbols:
        uni = UniverseResult(
            kept=[UniverseEntry(symbol=s) for s in symbols],
            watch_only=[],
            rejected=[],
        )
    else:
        uni = build_universe(provider=provider, as_of_date=as_of)

    # Prepare features and backtest stats
    features_by_symbol: Dict[str, Any] = {}
    backtest_stats_by_symbol: Dict[str, Any] = {}

    strat = StrategyDef(id="S1", name="Bias6 CrossUp", enabled=True, event_rule={"name": "bias6_cross_up", "params": {}}, lookback_days=250, forward_days=[2, 5, 10], min_samples=5)

    def load_feat(sym: str):
        df_raw = provider.get_daily(sym, start=None, end=as_of)
        df_norm, _ = normalize_daily_ohlcv(df_raw)
        feat = compute_indicators(df_norm, None)
        feat = feat.copy()
        feat.attrs["symbol"] = sym
        return feat

    for entry in list(uni.kept) + list(uni.watch_only):
        sym = entry.symbol
        try:
            feat = load_feat(sym)
            features_by_symbol[sym] = feat
            stats = run_event_backtest(feat, strat)
            backtest_stats_by_symbol[sym] = stats
        except Exception:
            continue

    # Rank
    result = rank_candidates(uni, features_by_symbol, backtest_stats_by_symbol, champion_state=None, config=None)
    top_items = result.top[:topk]

    # Convert dataclasses to dict for output
    def to_dict_item(it: PickItem) -> Dict[str, Any]:
        return {
            "symbol": it.symbol,
            "name": it.name,
            "sector": it.sector,
            "indicators": it.indicators,
            "noise_level": it.noise_level,
            "strategy_attribution": it.strategy_attribution,
            "backtest": it.backtest.__dict__,
            "risk_constraints": it.risk_constraints,
            "actions": it.actions,
            "time_stop": it.time_stop,
            "events": it.events,
            "score": it.score,
        }

    data = {
        "top": [to_dict_item(x) for x in top_items],
        "kept_count": result.kept_count,
        "watch_count": result.watch_count,
        "rejected_count": result.rejected_count,
    }
    return ToolResult(ok=True, message=f"排名完成: {len(top_items)} / kept={result.kept_count} watch={result.watch_count}", data=data)


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
