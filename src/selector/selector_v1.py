from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


@dataclass
class SelectorConfig:
    trend_window: int = 20
    momentum_window: int = 5
    liquidity_window: int = 5
    vol_penalty_window: int = 20
    ann_positive_keywords: Tuple[str, ...] = (
        "增持",
        "回购",
        "高送转",
        "股东增持",
        "利润增长",
    )
    ann_negative_keywords: Tuple[str, ...] = (
        "减持",
        "预亏",
        "亏损",
        "停产",
        "诉讼",
    )


def explainable_score(daily: pd.DataFrame, anns_today: pd.DataFrame, cfg: SelectorConfig) -> pd.DataFrame:
    """Compute V1 explainable score using only information available up to previous day.

    Inputs:
    - daily: DataFrame with columns [ts_code, trade_date, close, open, high, low, vol, amount]
             containing at least the previous N days until prev trade date.
    - anns_today: DataFrame with [ts_code, ann_date, title, category] for the target trade date.

    Output: DataFrame with per ts_code: score, tags (list of strings joined by ';')
    """
    if daily.empty:
        return pd.DataFrame(columns=["ts_code", "score", "tags"])  # pragma: no cover - trivial

    daily = daily.sort_values(["ts_code", "trade_date"]).copy()

    def _z(x: pd.Series) -> pd.Series:
        mu = x.mean()
        sd = x.std(ddof=0) or 1.0
        return (x - mu) / sd

    # Trend: 20d slope via linear fit of log close
    scores: List[pd.DataFrame] = []
    g = daily.groupby("ts_code", group_keys=False)

    def _trend(group: pd.DataFrame) -> float:
        c = group["close"].tail(cfg.trend_window)
        if len(c) < cfg.trend_window:
            return np.nan
        y = np.log(c.values)
        x = np.arange(len(y))
        slope = np.polyfit(x, y, 1)[0]
        return slope

    trend = g.apply(_trend).rename("trend")

    # Momentum: last 5d return
    def _mom(group: pd.DataFrame) -> float:
        c = group["close"].tail(cfg.momentum_window + 1)
        if len(c) < cfg.momentum_window + 1:
            return np.nan
        return float(c.iloc[-1] / c.iloc[0] - 1.0)

    momentum = g.apply(_mom).rename("momentum")

    # Liquidity: 5d average amount
    def _liq(group: pd.DataFrame) -> float:
        a = group["amount"].tail(cfg.liquidity_window)
        if len(a) < cfg.liquidity_window:
            return np.nan
        return float(a.mean())

    liquidity = g.apply(_liq).rename("liquidity")

    # Volatility penalty: 20d std of returns
    def _volp(group: pd.DataFrame) -> float:
        c = group["close"].pct_change().tail(cfg.vol_penalty_window)
        if len(c) < cfg.vol_penalty_window:
            return np.nan
        return float(c.std(ddof=0))

    vol_pen = g.apply(_volp).rename("vol_pen")

    feats = pd.concat([trend, momentum, liquidity, vol_pen], axis=1).reset_index()
    # Normalize features
    feats["trend_z"] = _z(feats["trend"].fillna(0))
    feats["momentum_z"] = _z(feats["momentum"].fillna(0))
    feats["liquidity_z"] = _z(np.log1p(feats["liquidity"].clip(lower=0))).fillna(0)
    feats["vol_pen_z"] = _z(feats["vol_pen"].fillna(0))

    # Score: trend + momentum + liquidity - vol_penalty
    feats["base_score"] = feats["trend_z"] + feats["momentum_z"] + 0.5 * feats["liquidity_z"] - 0.5 * feats["vol_pen_z"]

    # Announcement adjustments
    anns_today = anns_today.copy()
    anns_today["title"] = anns_today.get("title", "").astype(str)
    anns_today["adjust"] = 0.0
    pos_kw = cfg.ann_positive_keywords
    neg_kw = cfg.ann_negative_keywords
    anns_today.loc[anns_today["title"].str.contains("|".join(pos_kw), na=False), "adjust"] += 0.5
    anns_today.loc[anns_today["title"].str.contains("|".join(neg_kw), na=False), "adjust"] -= 0.5
    ann_adj = anns_today.groupby("ts_code")["adjust"].sum().rename("ann_adj")

    out = feats.merge(ann_adj, on="ts_code", how="left").fillna({"ann_adj": 0.0})
    out["score"] = out["base_score"] + out["ann_adj"]

    # tags for interpretability
    tags: List[str] = []
    def mk_tags(r: pd.Series) -> str:
        t: List[str] = []
        if r["trend_z"] > 0.8:
            t.append("trend_up")
        if r["momentum_z"] > 0.8:
            t.append("mom_hot")
        if r["liquidity_z"] < -0.8:
            t.append("illiquid")
        if r["vol_pen_z"] > 0.8:
            t.append("volatile")
        if r["ann_adj"] > 0:
            t.append("ann_pos")
        if r["ann_adj"] < 0:
            t.append("ann_neg")
        return ";".join(t)

    out["tags"] = out.apply(mk_tags, axis=1)
    return out[["ts_code", "score", "tags"]].sort_values("score", ascending=False)

