# 简介：筹码/成本带估算。提供 A/B 两种模型估算平均成本与 90% 带，
# 并输出置信度等统计，供交易计划参考。
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple
import numpy as np
import pandas as pd


@dataclass
class ChipResult:
    avg_cost: float
    profit_ratio: float
    band_90_low: float
    band_90_high: float
    concentration_90: float
    dist_to_90_high_pct: float
    confidence: str
    model_used: str
    sample_n: int


def _model_a(df: pd.DataFrame, float_shares: float | None = None) -> Tuple[ChipResult | None, Dict[str, Any]]:
    meta: Dict[str, Any] = {"model": "A"}
    x = df.copy()
    # estimate turnover
    turn = None
    if "turnover" in x.columns:
        turn = x["turnover"].astype(float) / 100.0
    elif float_shares and float_shares > 0:
        turn = x["volume"].astype(float) / float_shares
    else:
        return None, {**meta, "reason": "no_turnover"}
    vwap = (x["high"] + x["low"] + x["close"]) / 3.0
    weights = []
    prices = []
    w_remain = 0.0
    for i in range(len(x)):
        t = max(0.0, min(1.0, float(turn.iloc[i])))
        persist = (1.0 - t)
        w_remain = w_remain * persist + t
        weights.append(t)
        prices.append(float(vwap.iloc[i]))
    if sum(weights) <= 0:
        return None, {**meta, "reason": "zero_weights"}
    prices_arr = np.array(prices)
    w = np.array(weights)
    w = w / w.sum()
    avg_cost = float((prices_arr * w).sum())
    # 90% band using weighted quantiles (approximate via repetition scale)
    repeat = np.maximum(1, (w * 1000).astype(int))
    expanded = np.repeat(prices_arr, repeat)
    low = float(np.quantile(expanded, 0.05))
    high = float(np.quantile(expanded, 0.95))
    close = float(x["close"].iloc[-1])
    profit_ratio = float((expanded < close).mean())
    conc = float(np.mean((expanded >= low) & (expanded <= high)))
    dist_high_pct = (high - close) / high if high != 0 else 0.0
    conf = "high" if len(expanded) >= 200 else ("medium" if len(expanded) >= 80 else "low")
    return (
        ChipResult(
            avg_cost=avg_cost,
            profit_ratio=profit_ratio,
            band_90_low=low,
            band_90_high=high,
            concentration_90=conc,
            dist_to_90_high_pct=float(dist_high_pct),
            confidence=conf,
            model_used="A",
            sample_n=int(len(expanded)),
        ),
        meta,
    )


def _model_b(df: pd.DataFrame) -> Tuple[ChipResult, Dict[str, Any]]:
    meta: Dict[str, Any] = {"model": "B"}
    x = df.copy()
    vwap = (x["high"] + x["low"] + x["close"]) / 3.0
    volume = x["volume"].astype(float)
    # price bins by percentile of vwap
    q = np.linspace(0.0, 1.0, 51)
    cuts = np.quantile(vwap, q)
    idx = np.digitize(vwap, cuts, right=True)
    # Accumulate volume per bin and expand by basic repetition
    vol_bin = {}
    for i, b in enumerate(idx):
        vol_bin.setdefault(b, 0.0)
        vol_bin[b] += float(volume.iloc[i])
    arr = []
    for b, vol in vol_bin.items():
        price = float(cuts[min(max(b, 0), len(cuts) - 1)])
        rep = max(1, int(vol / max(1.0, volume.mean())))
        arr.extend([price] * rep)
    expanded = np.array(arr)
    avg_cost = float(np.mean(expanded)) if len(expanded) else float(vwap.iloc[-1])
    low = float(np.quantile(expanded, 0.05)) if len(expanded) else float(vwap.min())
    high = float(np.quantile(expanded, 0.95)) if len(expanded) else float(vwap.max())
    close = float(x["close"].iloc[-1])
    profit_ratio = float((expanded < close).mean()) if len(expanded) else 0.5
    conc = float(np.mean((expanded >= low) & (expanded <= high))) if len(expanded) else 1.0
    dist_high_pct = (high - close) / high if high != 0 else 0.0
    conf = "medium" if len(expanded) >= 100 else "low"
    return (
        ChipResult(
            avg_cost=avg_cost,
            profit_ratio=profit_ratio,
            band_90_low=low,
            band_90_high=high,
            concentration_90=conc,
            dist_to_90_high_pct=float(dist_high_pct),
            confidence=conf,
            model_used="B",
            sample_n=int(len(expanded)),
        ),
        meta,
    )


def compute_chip(df: pd.DataFrame, float_shares: float | None = None) -> Tuple[ChipResult, Dict[str, Any]]:
    a, meta_a = _model_a(df, float_shares)
    if a is not None:
        return a, meta_a
    b, meta_b = _model_b(df)
    return b, meta_b
