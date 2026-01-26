from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple
import pandas as pd


@dataclass
class Candidate:
    rank: int
    ts_code: str
    score: float
    name: str | None = None
    tags: str | None = None


def build_universe(
    stock_basic: pd.DataFrame,
    namechange: pd.DataFrame,
    daily_latest: pd.DataFrame,
    min_list_days: int,
    exclude_st: bool,
    min_amount: float,
    min_vol: int,
) -> pd.DataFrame:
    df = stock_basic.copy()

    # 不做名称弱匹配ST过滤；若上游未提供完备的ST区间，这里不进行任何替代过滤

    # merge with latest liquidity info
    if not daily_latest.empty:
        merged = df.merge(daily_latest[['ts_code','vol','amount','trade_date']], on='ts_code', how='left')
    else:
        merged = df.copy()

    # filters
    if 'amount' in merged:
        merged['amount'] = pd.to_numeric(merged['amount'], errors='coerce')
        merged = merged[(merged['amount'].fillna(0) >= min_amount)]
    if 'vol' in merged:
        merged['vol'] = pd.to_numeric(merged['vol'], errors='coerce')
        merged = merged[(merged['vol'].fillna(0) >= min_vol)]

    # list days filter when list_date is available
    if 'list_date' in merged:
        # This requires latest trade_date; if missing, skip
        if 'trade_date' in merged and merged['trade_date'].notna().any():
            last_date = merged['trade_date'].dropna().astype(str).max()
            # approximate by days difference on YYYYMMDD
            merged = merged[merged['list_date'].astype(str) <= last_date]

    merged = merged.drop_duplicates('ts_code').reset_index(drop=True)
    return merged


def score_simple(
    daily_df: pd.DataFrame,
    weekly_df: pd.DataFrame | None,
    monthly_df: pd.DataFrame | None,
) -> float:
    # Simple interpretable score: momentum + liquidity - volatility penalty
    score = 0.0
    if not daily_df.empty:
        daily_df = daily_df.sort_values('trade_date')
        close = daily_df['close']
        if len(close) >= 60:
            mom20 = (close.iloc[-1] / close.iloc[-21]) - 1
            mom60 = (close.iloc[-1] / close.iloc[-61]) - 1 if len(close) >= 61 else 0
            score += 0.6 * mom20 + 0.4 * mom60
        if 'amount' in daily_df:
            score += 0.000000001 * daily_df['amount'].tail(20).mean()  # scale down
        if len(close) >= 20:
            vol20 = close.tail(20).pct_change().std()
            if pd.notna(vol20):
                score -= 0.5 * float(vol20)
    return float(score)


def select_top_k(
    universe_df: pd.DataFrame,
    daily_bars: dict[str, pd.DataFrame],
    weekly_bars: dict[str, pd.DataFrame] | None,
    monthly_bars: dict[str, pd.DataFrame] | None,
    top_k: int,
) -> List[Candidate]:
    scores: List[Tuple[str, float]] = []
    for ts_code in universe_df['ts_code']:
        ddf = daily_bars.get(ts_code, pd.DataFrame())
        wdf = weekly_bars.get(ts_code, pd.DataFrame()) if weekly_bars else None
        mdf = monthly_bars.get(ts_code, pd.DataFrame()) if monthly_bars else None
        s = score_simple(ddf, wdf, mdf)
        scores.append((ts_code, s))
    scores.sort(key=lambda x: x[1], reverse=True)
    out: List[Candidate] = []
    for i, (code, s) in enumerate(scores[:top_k], start=1):
        name = None
        if 'name' in universe_df.columns:
            row = universe_df.loc[universe_df['ts_code'] == code]
            if not row.empty:
                name = row.iloc[0].get('name')
        out.append(Candidate(rank=i, ts_code=code, score=float(s), name=name or None, tags=None))
    return out
