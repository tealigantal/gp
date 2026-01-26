from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import math
import pandas as pd

from ..config import AppConfig
from ..strategy.base import Strategy, OrderIntent
from ..storage import load_parquet, min5_bar_path, daily_bar_path


@dataclass
class Position:
    ts_code: str
    shares: int
    cost: float
    buy_date: str  # YYYYMMDD


def in_trading_window(hhmmss: str) -> bool:
    # 允许连续竞价与收盘集合竞价（大致窗口）
    h, m, s = map(int, hhmmss.split(':'))
    t = h * 10000 + m * 100 + s
    return (
        (93000 <= t <= 113000) or
        (130000 <= t <= 145700) or
        (145700 <= t <= 150000)
    )


def next_bar_open_price(bar: pd.Series, side: str, slippage_bps: int) -> float:
    px = float(bar['open'])
    slip = (slippage_bps / 10000.0)
    return px * (1 + slip if side == 'buy' else 1 - slip)


def one_word_bar(bar: pd.Series) -> bool:
    return (bar['open'] == bar['high'] == bar['low'] == bar['close']) and (float(bar.get('vol', 0)) == 0.0)


def txn_fees(amount: float, fees_cfg) -> float:
    # commission capped by commission_cap (rate)
    comm = min(amount * fees_cfg.commission_rate, amount * fees_cfg.commission_cap)
    comm = max(comm, fees_cfg.min_commission)
    transfer = amount * fees_cfg.transfer_fee_rate
    return comm + transfer


class BacktestEngine:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg

    def _load_minute_bars(self, ts_code: str, yyyymmdd: str) -> pd.DataFrame:
        p = min5_bar_path(self.cfg.paths.data_root, ts_code, yyyymmdd)
        df = load_parquet(p)
        if df.empty:
            return df
        # ensure types and sort
        df = df.sort_values('trade_time').reset_index(drop=True)
        return df

    def _load_daily(self, ts_code: str) -> pd.DataFrame:
        p = daily_bar_path(self.cfg.paths.data_root, ts_code)
        df = load_parquet(p)
        if not df.empty:
            df = df.sort_values('trade_date').reset_index(drop=True)
        return df

    def _trade_limit_prices(self, ts_code: str, date: str) -> Tuple[Optional[float], Optional[float]]:
        # approximate using previous close * (1 ± 10%)
        ddf = self._load_daily(ts_code)
        if ddf.empty:
            return None, None
        row = ddf[ddf['trade_date'] < date].tail(1)
        if row.empty:
            return None, None
        pre_close = float(row.iloc[0]['close'])
        return pre_close * 1.1, pre_close * 0.9

    def run_weekly(self, start: str, end: str, strategies: Dict[str, object], min_missing_threshold: float = 0.1) -> Path:
        results_dir = self.cfg.paths.results_root / f"run_{self.cfg.experiment.run_id}"
        results_dir.mkdir(parents=True, exist_ok=True)

        trades_rows: List[str] = ["id,date,ts_code,side,price,shares,strategy"]
        equity_rows: List[str] = ["date,nav"]
        summary_rows: List[str] = ["week_start,week_end,strategy,win_rate,ret,drawdown,trades,not_filled"]

        cash = self.cfg.experiment.initial_cash
        positions: Dict[str, Position] = {}
        not_filled_count = 0
        missing_min5_days: Dict[str, List[str]] = {}

        # Build trading days from available candidate files (fallback to daily bars dates is possible, but we keep simple)
        # We scan daily bar files for dates in range
        all_dates: List[str] = []
        for p in (self.cfg.paths.data_root / 'bars' / 'daily').glob('ts_code=*.parquet'):
            df = load_parquet(p)
            if df.empty:
                continue
            dates = df[(df['trade_date'] >= start) & (df['trade_date'] <= end)]['trade_date'].tolist()
            all_dates.extend(dates)
        all_dates = sorted(sorted(set(all_dates)))
        if not all_dates:
            raise RuntimeError("未找到回测区间内的日线数据，无法开始回测")

        # naive weekly segmentation by calendar week (every Mon-Fri in sequence)
        def week_of(d: str) -> str:
            return d[:6] + "W"  # coarse id

        trade_id = 0
        last_nav = cash
        week_first = all_dates[0]
        week_trades: List[Tuple[str, float]] = []  # (strategy, pnl)

        # Only one strategy key for now if provided
        strat_name = list(strategies.keys())[0] if strategies else 'baseline'
        strat = strategies.get(strat_name)

        for date in all_dates:
            # Load candidate list; if not present, skip trading that day
            cand_path = self.cfg.paths.universe_root / f"candidate_pool_{date}.csv"
            if not cand_path.exists():
                # no candidates -> mark equity and continue
                equity_rows.append(f"{date},{last_nav:.2f}")
                continue
            cands_df = pd.read_csv(cand_path)
            candidates = cands_df['ts_code'].astype(str).tolist()

            # Branch by strategy type
            is_daily = hasattr(strat, 'requires_minutes') and getattr(strat, 'requires_minutes') is False if strat else False

            if is_daily:
                # Daily-only: buy at today's open for topK; sell yesterday's holdings at today's open (T+1)
                # First, execute sells for positions that can be sold (T+1)
                sell_syms = [k for k, p in positions.items() if date > p.buy_date]
                for ts in sell_syms:
                    # price: today's open from daily bar
                    ddf = self._load_daily(ts)
                    row = ddf[ddf['trade_date'] == date]
                    if row.empty:
                        continue  # strict but keep day going; doctor会事先检查
                    price = float(row.iloc[0]['open'])
                    shares = positions[ts].shares
                    amount = price * shares
                    fees = txn_fees(amount, self.cfg.fees) + amount * self.cfg.fees.stamp_duty_rate
                    cash += amount - fees
                    pnl = (price - positions[ts].cost) * shares - fees
                    week_trades.append((strat_name, pnl))
                    trade_id += 1
                    trades_rows.append(f"{trade_id},{date},{ts},sell,{price:.4f},{shares},{strat_name}")
                    positions.pop(ts, None)

                # Then buys for topK candidates at today's open
                k = getattr(strat, 'params').buy_top_k if hasattr(strat, 'params') else 1
                for ts in candidates[:k]:
                    ddf = self._load_daily(ts)
                    row = ddf[ddf['trade_date'] == date]
                    if row.empty:
                        continue
                    price = float(row.iloc[0]['open'])
                    per_cash = cash * (getattr(strat, 'params').per_stock_cash if hasattr(strat, 'params') else 0.25)
                    shares = int(math.floor(per_cash / price / 100.0) * 100)
                    if shares <= 0:
                        continue
                    amount = price * shares
                    fees = txn_fees(amount, self.cfg.fees)
                    cash -= amount + fees
                    positions[ts] = Position(ts, shares, price, buy_date=date)
                    trade_id += 1
                    trades_rows.append(f"{trade_id},{date},{ts},buy,{price:.4f},{shares},{strat_name}")

                # Force close on rough Friday boundary: if next day belongs to another week or it's the last day
                # We approximate Friday by checking next date week id
                idx = all_dates.index(date)
                is_last = (idx == len(all_dates) - 1)
                next_week = None if is_last else week_of(all_dates[idx + 1])
                if is_last or next_week != week_of(date):
                    for ts, pos in list(positions.items()):
                        ddf = self._load_daily(ts)
                        row = ddf[ddf['trade_date'] == date]
                        if row.empty:
                            continue
                        price = float(row.iloc[0]['close'])
                        shares = pos.shares
                        amount = price * shares
                        fees = txn_fees(amount, self.cfg.fees) + amount * self.cfg.fees.stamp_duty_rate
                        cash += amount - fees
                        pnl = (price - pos.cost) * shares - fees
                        week_trades.append((strat_name, pnl))
                        trade_id += 1
                        trades_rows.append(f"{trade_id},{date},{ts},sell,{price:.4f},{shares},{strat_name}")
                        positions.pop(ts, None)

                # Mark NAV
                mtm = 0.0
                for ts, pos in positions.items():
                    ddf = self._load_daily(ts)
                    row = ddf[ddf['trade_date'] == date]
                    if not row.empty:
                        last_close = float(row.iloc[0]['close'])
                        mtm += last_close * pos.shares
                last_nav = cash + mtm
                equity_rows.append(f"{date},{last_nav:.2f}")
                # Continue to next date
                continue

            # Strategy day start (minute-based)
            if strat:
                strat.on_day_start(date, candidates, context={})

            # Iterate per candidate symbol minute bars
            for ts in candidates:
                mb = self._load_minute_bars(ts, date)
                if mb.empty:
                    not_filled_count += 1
                    missing_min5_days.setdefault(date, []).append(ts)
                    continue
                # schedule map for next-bar execution
                pending_side: Optional[str] = None
                for i in range(len(mb)):
                    bar = mb.iloc[i]
                    t = str(bar['trade_time'])
                    hhmmss = t.split(' ')[1] if ' ' in t else t[-8:]
                    if not in_trading_window(hhmmss):
                        continue

                    # Execute pending order at this bar's open
                    if pending_side:
                        # limit-up/down check
                        if one_word_bar(bar):
                            not_filled_count += 1
                            # keep pending until first tradable bar
                            continue
                        # T+1 check for sells
                        if pending_side == 'sell':
                            pos = positions.get(ts)
                            if not pos:
                                pending_side = None
                            else:
                                # T+1: only if today > buy_date
                                if date <= pos.buy_date:
                                    # cannot sell today
                                    continue
                        price = next_bar_open_price(bar, pending_side, self.cfg.fees.slippage_bps)
                        if pending_side == 'buy':
                            # position size by per_stock_cash fraction
                            per_cash = cash * 0.25  # default fraction if strategy doesn't expose
                            shares = int(math.floor(per_cash / price / 100.0) * 100)
                            if shares <= 0:
                                pending_side = None
                                continue
                            amount = price * shares
                            fees = txn_fees(amount, self.cfg.fees)
                            cash -= amount + fees
                            positions[ts] = Position(ts, shares, price, buy_date=date)
                            trade_id += 1
                            trades_rows.append(f"{trade_id},{date},{ts},buy,{price:.4f},{shares},{strat_name}")
                        else:
                            pos = positions.get(ts)
                            if pos and pos.shares > 0:
                                shares = pos.shares
                                amount = price * shares
                                fees = txn_fees(amount, self.cfg.fees) + amount * self.cfg.fees.stamp_duty_rate
                                cash += amount - fees
                                pnl = (price - pos.cost) * shares - fees
                                week_trades.append((strat_name, pnl))
                                trade_id += 1
                                trades_rows.append(f"{trade_id},{date},{ts},sell,{price:.4f},{shares},{strat_name}")
                                positions.pop(ts, None)
                        pending_side = None

                    # Generate signal on current bar close, execute next bar open
                    if strat:
                        intent = strat.on_bar({'trade_time': t, 'ts_code': ts, 'open': bar['open'], 'high': bar['high'], 'low': bar['low'], 'close': bar['close']}, context={'candidates': candidates, 'today': date})
                        if intent:
                            pending_side = intent.side

                # End of symbol minute series

            # End of day: mark NAV (positions MTM at last close if available)
            mtm = 0.0
            for ts, pos in positions.items():
                mb = self._load_minute_bars(ts, date)
                if not mb.empty:
                    last_close = float(mb['close'].iloc[-1])
                    mtm += last_close * pos.shares
            last_nav = cash + mtm
            equity_rows.append(f"{date},{last_nav:.2f}")

            # Week boundary: if Friday (approx by week id change) then force close
            if week_of(date) != week_of(week_first):
                # summarize week
                if week_trades:
                    wins = sum(1 for _, pnl in week_trades if pnl > 0)
                    total = len(week_trades)
                    win_rate = wins / total if total else 0.0
                    ret = (last_nav / self.cfg.experiment.initial_cash - 1.0)
                    drawdown = 0.0  # placeholder
                    summary_rows.append(f"{week_first},{date},{strat_name},{win_rate:.3f},{ret:.3f},{drawdown:.3f},{total},{not_filled_count}")
                week_first = date
                week_trades.clear()

            # After finishing day for minute-based strategy, enforce missing threshold
            if not is_daily and candidates:
                miss = len(missing_min5_days.get(date, []))
                ratio = miss / max(1, len(candidates))
                if ratio > min_missing_threshold:
                    missing_list = ','.join(missing_min5_days.get(date, []))
                    raise RuntimeError(f"分钟线缺失比例 {ratio:.1%} 超过阈值 {min_missing_threshold:.0%} 于 {date}; 缺失代码: {missing_list}. 请先运行 fetch 抓取min5 或切换 --min-provider eastmoney_curl")

        # Write outputs
        # Append final week summary if any
        if week_trades:
            wins = sum(1 for _, pnl in week_trades if pnl > 0)
            total = len(week_trades)
            win_rate = wins / total if total else 0.0
            ret = (last_nav / self.cfg.experiment.initial_cash - 1.0)
            drawdown = 0.0
            summary_rows.append(f"{week_first},{all_dates[-1]},{strat_name},{win_rate:.3f},{ret:.3f},{drawdown:.3f},{total},{not_filled_count}")
        (results_dir / 'trades.csv').write_text("\n".join(trades_rows), encoding='utf-8')
        (results_dir / 'daily_equity.csv').write_text("\n".join(equity_rows), encoding='utf-8')
        (results_dir / 'weekly_summary.csv').write_text("\n".join(summary_rows), encoding='utf-8')
        (results_dir / 'metrics.json').write_text("{}", encoding='utf-8')
        return results_dir
