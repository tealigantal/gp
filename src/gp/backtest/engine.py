from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..datapool import DataPool
from ..features.core import compute_features_for
from ..strategies.dsl import StrategyDSL


@dataclass
class Trade:
    date: date
    code: str
    action: str
    price: float
    qty: int
    reason: str


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    metrics: Dict[str, float]


def backtest_daily_t1(dp: DataPool, strategy: StrategyDSL, start: date, end: date, codes: List[str]) -> BacktestResult:
    # Very simplified daily close-confirm -> next open trade; time stop
    records: List[Dict] = []
    for code in codes:
        bars = dp.read_bars(code, start, end)
        if bars.empty:
            continue
        f = compute_features_for(dp, code)
        f = f.merge(bars, on=["date","code"], suffixes=("_f",""), how="right")
        pos = 0
        entry_price = 0.0
        entry_date: Optional[pd.Timestamp] = None
        for i in range(1, len(f)):
            row_y = f.iloc[i-1]
            row = f.iloc[i]
            d = pd.to_datetime(row["date"]).date()
            if pos == 0:
                # Setup/confirm at previous close
                rsi_ok = float(row_y["rsi2"]) <= strategy.setup_conditions.params.get("rsi2_max", 15.0)
                bias_ok = float(row_y["bias6"]) <= strategy.setup_conditions.params.get("bias6_min", -6.0)
                if rsi_ok and bias_ok:
                    # Buy at today's open, T+1
                    price = float(row["open"]) if not pd.isna(row["open"]) else float(row["close"]) 
                    qty = max(0, int((10000 * strategy.position_rules.risk_budget_pct) // price) * strategy.position_rules.lot_size)
                    if qty > 0:
                        pos = qty
                        entry_price = price
                        entry_date = pd.to_datetime(row["date"]).date()
                        records.append({"date": d, "code": code, "action": "BUY", "price": price, "qty": qty, "reason": "RSI2 pullback"})
            else:
                # time stop 3 days after entry
                if entry_date and (d - entry_date).days >= 3:
                    price = float(row["open"]) if not pd.isna(row["open"]) else float(row["close"]) 
                    records.append({"date": d, "code": code, "action": "SELL", "price": price, "qty": pos, "reason": "time_stop"})
                    pos = 0
                    entry_price = 0.0
                    entry_date = None
    if records:
        trades = pd.DataFrame(records)
    else:
        trades = pd.DataFrame(columns=["date","code","action","price","qty","reason"])

    # Compute PnL per round trip and metrics (2/5/10 day forward close change proxy)
    # Simple win rate: SELL price > prior BUY price
    n_trades = len(trades) // 2
    wins = 0
    rets = []
    for i in range(0, len(trades), 2):
        if i+1 >= len(trades):
            break
        if trades.iloc[i]["action"] != "BUY" or trades.iloc[i+1]["action"] != "SELL":
            continue
        r = (trades.iloc[i+1]["price"] - trades.iloc[i]["price"]) / trades.iloc[i]["price"]
        rets.append(r)
        wins += 1 if r > 0 else 0
    win_rate = wins / n_trades if n_trades > 0 else 0.0
    total_return = float(np.nansum(rets))
    max_dd = float(np.min([0.0] + list(np.cumsum(rets) - np.maximum.accumulate(np.cumsum(rets)))))
    metrics = {
        "n_trades": float(n_trades),
        "win_rate": float(win_rate),
        "total_return": float(total_return),
        "max_drawdown": float(abs(max_dd)),
    }
    return BacktestResult(trades=trades, metrics=metrics)

