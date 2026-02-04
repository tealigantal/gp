from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import pandas as pd

from .datapool import DataPool


Env = Literal['A','B','C','D']


@dataclass
class MarketState:
    env: Env
    score_q: int  # Q0..Q3 mapped to 0..3
    notes: str


def classify_env(dp: DataPool, ref_date: date) -> MarketState:
    # Deterministic rules based on index close vs MA20 and breadth proxy (advancers/decliners)
    idx = dp.con.execute(
        """
        SELECT date, close FROM index_daily
        WHERE index_code = 'SH000001' AND date <= ?
        ORDER BY date
        """,
        [ref_date],
    ).fetch_df()
    if idx.empty:
        return MarketState(env='C', score_q=1, notes='指数缺失，降级为C环境，Q1')
    idx['ma20'] = idx['close'].rolling(20).mean()
    latest = idx.iloc[-1]
    env = 'A' if latest['close'] > latest['ma20'] else 'C'
    # Breadth proxy
    br = dp.con.execute(
        "SELECT * FROM market_breadth WHERE date = ?",
        [ref_date],
    ).fetch_df()
    q = 1
    bnote = ''
    if not br.empty:
        row = br.iloc[0]
        adv = row.get('advancers') or 0
        dec = row.get('decliners') or 0
        if adv + dec > 0:
            ratio = adv / (adv + dec)
            if ratio >= 0.65:
                q = 3
                env = 'A'
                bnote = f'涨多比 {ratio:.2f}'
            elif ratio >= 0.55:
                q = 2
                bnote = f'涨多比 {ratio:.2f}'
            elif ratio <= 0.45:
                q = 0
                env = 'D'
                bnote = f'涨多比 {ratio:.2f}'
    notes = f'上证收盘 vs MA20: {env}; {bnote or "breadth缺失"}'
    return MarketState(env=env, score_q=q, notes=notes)

