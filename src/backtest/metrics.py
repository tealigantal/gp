from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np
import pandas as pd


@dataclass
class TradeStats:
    win_rate: float
    expectancy: float
    payoff_ratio: float
    max_drawdown: float
    trades: int
    buy_fail: int
    sell_fail: int


def equity_max_drawdown(equity: pd.Series) -> float:
    peak = -np.inf
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = (peak - v) / peak if peak > 0 else 0.0
        mdd = max(mdd, dd)
    return float(mdd)


def summarize(trades: pd.DataFrame, daily_equity: pd.DataFrame, fail_counts: Dict[str, int]) -> TradeStats:
    if trades.empty:
        return TradeStats(0.0, 0.0, 0.0, 0.0, 0, fail_counts.get("buy_fail", 0), fail_counts.get("sell_fail", 0))
    # Per trade PnL pairs: assume next SELL closes the BUY lot
    # For simplicity in this project, compute rough stats:
    pnl_list = []
    open_pos: Dict[str, Tuple[float, int]] = {}
    for r in trades.itertuples():
        if r.side == "BUY":
            open_pos[r.ts_code] = (r.price, r.shares)
        else:
            if r.ts_code in open_pos:
                buy_px, buy_sh = open_pos.pop(r.ts_code)
                sh = min(buy_sh, r.shares)
                pnl = (r.price - buy_px) * sh - r.fee  # fees simplified
                pnl_list.append(pnl)
    pnl_arr = np.array(pnl_list, dtype=float) if pnl_list else np.array([], dtype=float)
    wins = (pnl_arr > 0).sum()
    losses = (pnl_arr < 0).sum()
    win_rate = float(wins / len(pnl_arr)) if len(pnl_arr) else 0.0
    expectancy = float(pnl_arr.mean()) if len(pnl_arr) else 0.0
    avg_win = float(pnl_arr[pnl_arr > 0].mean()) if wins else 0.0
    avg_loss = float(-pnl_arr[pnl_arr < 0].mean()) if losses else 0.0
    payoff = float(avg_win / avg_loss) if avg_loss > 0 else 0.0

    mdd = equity_max_drawdown(daily_equity["equity"]) if not daily_equity.empty else 0.0
    return TradeStats(win_rate, expectancy, payoff, mdd, len(pnl_arr), fail_counts.get("buy_fail", 0), fail_counts.get("sell_fail", 0))

