# 简介：工具 - 策略打分与对比的命令行辅助，便于快速评估候选分数。
from __future__ import annotations

from typing import Any, List, Dict

from ..core.types import ToolResult
from ..providers.factory import get_provider
from .market_data import normalize_daily_ohlcv
from .signals import compute_indicators
from .backtest import StrategyDef, run_event_backtest


def _score_from_stats(stats) -> float:
    # 简单映射：0.7*wr5 + 0.3*max(avg5,0) - 风险（mdd过大轻微扣分）
    wr5 = float(getattr(stats, "win_rate_5", 0.0))
    avg5 = float(getattr(stats, "avg_return_5", 0.0))
    mdd10 = float(getattr(stats, "mdd10_avg", 0.0))
    pen = 0.0
    if mdd10 < -0.05:
        pen += min(0.1, abs(mdd10) / 2)
    base = 0.7 * wr5 + 0.3 * max(0.0, avg5)
    return max(0.0, min(1.0, base - pen))


def run_strategy_score(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    symbols: List[str] = args.get("symbols", [])
    topk: int = int(args.get("topk", 3) or 3)
    if not symbols:
        return ToolResult(ok=False, message="缺少 symbols")

    provider = get_provider()
    strat = StrategyDef(id="S1", name="Bias6 CrossUp", enabled=True, event_rule={"name": "bias6_cross_up", "params": {}}, lookback_days=250, forward_days=[2, 5, 10], min_samples=5)

    out: List[Dict[str, Any]] = []
    for sym in symbols:
        try:
            df_raw = provider.get_daily(sym, start=None, end=None)
            df_norm, _ = normalize_daily_ohlcv(df_raw)
            feat = compute_indicators(df_norm, None)
            feat.attrs["symbol"] = sym
            stats = run_event_backtest(feat, strat)
            score = _score_from_stats(stats)
            out.append({
                "symbol": sym,
                "score": round(float(score * 100.0), 2),
                "k": int(getattr(stats, "k", 0)),
                "wr5": float(getattr(stats, "win_rate_5", 0.0)),
                "avg5": float(getattr(stats, "avg_return_5", 0.0)),
                "mdd10": float(getattr(stats, "mdd10_avg", 0.0)),
            })
        except Exception as e:  # noqa: BLE001
            out.append({"symbol": sym, "error": str(e), "score": 0.0})

    out.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    out = out[:topk]
    return ToolResult(ok=True, message=f"已评分 {len(symbols)} 只，返回前 {len(out)}", data={"candidates": out})
