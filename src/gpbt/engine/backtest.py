from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import math
import pandas as pd

from ..config import AppConfig
from ..strategy.base import Strategy, OrderIntent
from ..storage import load_parquet, min5_bar_path, daily_bar_path
from ..doctor import run_doctor
import json as _json
import hashlib
import subprocess


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

    def run_weekly(self, start: str, end: str, strategies: Dict[str, object], min_missing_threshold: float = 0.1, ranked_map: Optional[Dict[str, List[str]]] = None) -> Path:
        results_root = self.cfg.paths.results_root / f"run_{self.cfg.experiment.run_id}"
        results_root.mkdir(parents=True, exist_ok=True)

        # Build trading days once
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

        def week_of(d: str) -> str:
            return d[:6] + "W"

        # vNext compare schema (net-based)
        compare_rows: List[str] = [
            "strategy,n_trades,win_rate,total_return_net,max_drawdown_net,turnover,no_fill_buy,no_fill_sell,forced_flat_count,status"
        ]
        costs_rows: List[str] = ["strategy,gross_return,net_return,turnover,fees_paid"]
        events_all: List[dict] = []

        for strat_name, strat in strategies.items():
            strat_dir = results_root / strat_name
            strat_dir.mkdir(parents=True, exist_ok=True)

            trades_rows: List[str] = ["id,date,ts_code,side,price,shares,strategy,reason"]
            equity_rows: List[str] = ["date,nav"]
            summary_rows: List[str] = ["week_start,week_end,strategy,win_rate,ret,drawdown,trades,not_filled"]

            cash = self.cfg.experiment.initial_cash
            positions: Dict[str, Position] = {}
            not_filled_buy = 0
            not_filled_sell = 0
            forced_flat_delayed = 0
            missing_min5_days: Dict[str, List[str]] = {}
            buy_intent_count = 0

            total_fees = 0.0
            total_buy_amt = 0.0
            total_sell_amt = 0.0

            last_nav = cash
            week_first = all_dates[0]
            week_trades: List[float] = []

            for date in all_dates:
                cand_path = self.cfg.paths.universe_root / f"candidate_pool_{date}.csv"
                if not cand_path.exists():
                    equity_rows.append(f"{date},{last_nav:.2f}")
                    continue
                cands_df = pd.read_csv(cand_path)
                candidates = cands_df['ts_code'].astype(str).tolist()
                if ranked_map and date in ranked_map:
                    # Override order to use LLM picks (only these)
                    candidates = ranked_map[date]

                is_daily = hasattr(strat, 'requires_minutes') and getattr(strat, 'requires_minutes') is False

                def open_count() -> int:
                    return sum(1 for _ in positions.values())

                if is_daily:
                    sell_syms = [k for k, p in positions.items() if date > p.buy_date]
                    for ts in sell_syms:
                        ddf = self._load_daily(ts)
                        row = ddf[ddf['trade_date'] == date]
                        if row.empty:
                            continue
                        price = float(row.iloc[0]['open'])
                        shares = positions[ts].shares
                        amount = price * shares
                        fees = txn_fees(amount, self.cfg.fees) + amount * self.cfg.fees.stamp_duty_rate
                        total_fees += fees
                        total_sell_amt += amount
                        cash += amount - fees
                        pnl = (price - positions[ts].cost) * shares - fees
                        week_trades.append(pnl)
                        trades_rows.append(f"{len(trades_rows)},{date},{ts},sell,{price:.4f},{shares},{strat_name},DAILY_EXIT")
                        events_all.append({'time': f"{date} 09:30:00", 'strategy': strat_name, 'code': ts, 'event_type': 'fill', 'side': 'sell', 'price': float(price), 'qty': int(shares), 'reason': 'DAILY_EXIT'})
                        positions.pop(ts, None)

                    k = getattr(getattr(strat, 'params', None), 'buy_top_k', 1)
                    per_stock_cash = getattr(getattr(strat, 'params', None), 'per_stock_cash', 0.25)
                    for ts in candidates[:k]:
                        if open_count() >= k:
                            break
                        ddf = self._load_daily(ts)
                        row = ddf[ddf['trade_date'] == date]
                        if row.empty:
                            continue
                        price = float(row.iloc[0]['open'])
                        shares = int(math.floor((cash * per_stock_cash) / price / 100.0) * 100)
                        if shares <= 0:
                            continue
                        amount = price * shares
                        fees = txn_fees(amount, self.cfg.fees)
                        total_fees += fees
                        total_buy_amt += amount
                        cash -= amount + fees
                        positions[ts] = Position(ts, shares, price, buy_date=date)
                        buy_intent_count += 1
                        trades_rows.append(f"{len(trades_rows)},{date},{ts},buy,{price:.4f},{shares},{strat_name},DAILY_ENTRY")
                        events_all.append({'time': f"{date} 09:30:00", 'strategy': strat_name, 'code': ts, 'event_type': 'fill', 'side': 'buy', 'price': float(price), 'qty': int(shares), 'reason': 'DAILY_ENTRY'})

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
                            total_fees += fees
                            total_sell_amt += amount
                            cash += amount - fees
                            pnl = (price - pos.cost) * shares - fees
                            week_trades.append(pnl)
                            trades_rows.append(f"{len(trades_rows)},{date},{ts},sell,{price:.4f},{shares},{strat_name},FORCE_FRIDAY")
                            events_all.append({'time': f"{date} 15:00:00", 'strategy': strat_name, 'code': ts, 'event_type': 'force_flat', 'side': 'sell', 'price': float(price), 'qty': int(shares), 'reason': 'FORCE_FRIDAY'})
                            positions.pop(ts, None)

                    mtm = 0.0
                    for ts, pos in positions.items():
                        ddf = self._load_daily(ts)
                        row = ddf[ddf['trade_date'] == date]
                        if not row.empty:
                            last_close = float(row.iloc[0]['close'])
                            mtm += last_close * pos.shares
                    last_nav = cash + mtm
                    equity_rows.append(f"{date},{last_nav:.2f}")
                    continue

                if strat:
                    strat.on_day_start(date, candidates, context={})
                exit_time = getattr(getattr(strat, 'params', None), 'exit_time', None)
                stop_loss_pct = getattr(getattr(strat, 'params', None), 'stop_loss_pct', 0.0) or 0.0
                take_profit_pct = getattr(getattr(strat, 'params', None), 'take_profit_pct', 0.0) or 0.0
                per_stock_cash = getattr(getattr(strat, 'params', None), 'per_stock_cash', 0.25)
                max_positions = getattr(getattr(strat, 'params', None), 'max_positions', 1)

                for ts in candidates:
                    mb = self._load_minute_bars(ts, date)
                    if mb.empty:
                        missing_min5_days.setdefault(date, []).append(ts)
                        continue
                    pending_side: Optional[str] = None
                    pending_reason: str = ''
                    for i in range(len(mb)):
                        bar = mb.iloc[i]
                        t = str(bar['trade_time'])
                        hhmmss = t.split(' ')[1] if ' ' in t else t[-8:]
                        if not in_trading_window(hhmmss):
                            continue

                        if pending_side:
                            if one_word_bar(bar):
                                if pending_side == 'buy':
                                    not_filled_buy += 1
                                else:
                                    not_filled_sell += 1
                                continue
                            if pending_side == 'sell':
                                pos = positions.get(ts)
                                if not pos or date <= pos.buy_date:
                                    continue
                            price = next_bar_open_price(bar, pending_side, self.cfg.fees.slippage_bps)
                            if pending_side == 'buy':
                                if open_count() >= max_positions:
                                    pending_side = None
                                    continue
                                shares = int(math.floor((cash * per_stock_cash) / price / 100.0) * 100)
                                if shares <= 0:
                                    pending_side = None
                                    continue
                                amount = price * shares
                                fees = txn_fees(amount, self.cfg.fees)
                                total_fees += fees
                                total_buy_amt += amount
                                cash -= amount + fees
                                positions[ts] = Position(ts, shares, price, buy_date=date)
                                buy_intent_count += 1
                                trades_rows.append(f"{len(trades_rows)},{date},{ts},buy,{price:.4f},{shares},{strat_name},{pending_reason}")
                                events_all.append({'time': t, 'strategy': strat_name, 'code': ts, 'event_type': 'fill', 'side': 'buy', 'price': float(price), 'qty': int(shares), 'reason': pending_reason})
                            else:
                                pos = positions.get(ts)
                                if pos and pos.shares > 0:
                                    shares = pos.shares
                                    amount = price * shares
                                    fees = txn_fees(amount, self.cfg.fees) + amount * self.cfg.fees.stamp_duty_rate
                                    total_fees += fees
                                    total_sell_amt += amount
                                    cash += amount - fees
                                    pnl = (price - pos.cost) * shares - fees
                                    week_trades.append(pnl)
                                    trades_rows.append(f"{len(trades_rows)},{date},{ts},sell,{price:.4f},{shares},{strat_name},{pending_reason}")
                                    events_all.append({'time': t, 'strategy': strat_name, 'code': ts, 'event_type': 'fill', 'side': 'sell', 'price': float(price), 'qty': int(shares), 'reason': pending_reason})
                                    positions.pop(ts, None)
                            pending_side = None

                        if strat:
                            intent = strat.on_bar({'trade_time': t, 'ts_code': ts, 'open': bar['open'], 'high': bar['high'], 'low': bar['low'], 'close': bar['close'], 'vol': bar.get('vol', 0)}, context={'candidates': candidates, 'today': date})
                            if intent and open_count() < max_positions:
                                pending_side = intent.side
                                pending_reason = intent.reason

                        pos = positions.get(ts)
                        if pos and date > pos.buy_date:
                            if exit_time and hhmmss == exit_time:
                                pending_side = 'sell'
                                pending_reason = 'FIXED_EXIT'
                            close_px = float(bar['close'])
                            if stop_loss_pct > 0 and close_px <= pos.cost * (1 - stop_loss_pct):
                                pending_side = 'sell'
                                pending_reason = 'STOP_LOSS'
                            if take_profit_pct > 0 and close_px >= pos.cost * (1 + take_profit_pct):
                                pending_side = 'sell'
                                pending_reason = 'TAKE_PROFIT'

                mtm = 0.0
                for ts, pos in positions.items():
                    mb = self._load_minute_bars(ts, date)
                    if not mb.empty:
                        last_close = float(mb['close'].iloc[-1])
                        mtm += last_close * pos.shares
                last_nav = cash + mtm
                equity_rows.append(f"{date},{last_nav:.2f}")

                if week_of(date) != week_of(week_first):
                    if week_trades:
                        wins = sum(1 for pnl in week_trades if pnl > 0)
                        total = len(week_trades)
                        win_rate = wins / total if total else 0.0
                        ret = (last_nav / self.cfg.experiment.initial_cash - 1.0)
                        drawdown = 0.0
                        summary_rows.append(f"{week_first},{date},{strat_name},{win_rate:.3f},{ret:.3f},{drawdown:.3f},{total},{not_filled_buy+not_filled_sell}")
                    week_first = date
                    week_trades.clear()

                if getattr(strat, 'requires_minutes', True) and candidates:
                    miss = len(missing_min5_days.get(date, []))
                    ratio = miss / max(1, len(candidates))
                    if ratio > min_missing_threshold:
                        missing_list = ','.join(missing_min5_days.get(date, []))
                        raise RuntimeError(f"分钟线缺失比例 {ratio:.1%} 超过阈值 {min_missing_threshold:.0%} 于 {date}; 缺失代码: {missing_list}. 请先运行 fetch 抓取min5 或切换 --min-provider eastmoney_curl")

            if week_trades:
                wins = sum(1 for pnl in week_trades if pnl > 0)
                total = len(week_trades)
                win_rate = wins / total if total else 0.0
                ret = (last_nav / self.cfg.experiment.initial_cash - 1.0)
                drawdown = 0.0
                summary_rows.append(f"{week_first},{all_dates[-1]},{strat_name},{win_rate:.3f},{ret:.3f},{drawdown:.3f},{total},{not_filled_buy+not_filled_sell}")

            n_tr = len(week_trades)
            if n_tr > 0:
                wins_list = [p for p in week_trades if p > 0]
                win_rate = len(wins_list) / n_tr
            else:
                win_rate = 0.0
            status = 'OK' if buy_intent_count>0 else 'NO_SIGNAL'
            (results_root / 'compare_strategies.csv').touch()
            net_ret = (last_nav / self.cfg.experiment.initial_cash - 1.0)
            turnover = (total_buy_amt + total_sell_amt) / max(1.0, self.cfg.experiment.initial_cash)
            compare_rows.append(f"{strat_name},{n_tr},{win_rate:.3f},{net_ret:.3f},0.000,{turnover:.6f},{not_filled_buy},{not_filled_sell},{forced_flat_delayed},{status}")

            (strat_dir / 'trades.csv').write_text("\n".join(trades_rows), encoding='utf-8')
            (strat_dir / 'daily_equity.csv').write_text("\n".join(equity_rows), encoding='utf-8')
            (strat_dir / 'weekly_summary.csv').write_text("\n".join(summary_rows), encoding='utf-8')
            # Per-strategy metrics with costs
            import json as _json
            net_ret = (last_nav / self.cfg.experiment.initial_cash - 1.0)
            gross_ret = net_ret + (total_fees / self.cfg.experiment.initial_cash)
            turnover = (total_buy_amt + total_sell_amt) / max(1.0, self.cfg.experiment.initial_cash)
            (strat_dir / 'metrics.json').write_text(_json.dumps({
                'gross_return': gross_ret,
                'net_return': net_ret,
                'turnover': turnover,
                'fees_paid': total_fees,
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            costs_rows.append(f"{strat_name},{gross_ret:.6f},{net_ret:.6f},{turnover:.6f},{total_fees:.2f}")

        (results_root / 'compare_strategies.csv').write_text("\n".join(compare_rows), encoding='utf-8')
        (results_root / 'costs.csv').write_text("\n".join(costs_rows), encoding='utf-8')
        # Run-level events
        if events_all:
            with open(results_root / 'events.jsonl', 'w', encoding='utf-8') as f:
                for ev in events_all:
                    f.write(_json.dumps(ev, ensure_ascii=False) + '\n')
        # Manifest (vNext)
        manifest = {
            'git_commit': _safe_git_commit(),
            'configs_hash': _hash_configs(self.cfg),
            'engine_policy': {
                'bar_close_confirm': True,
                'next_open_fill': True,
                't_plus_one': True,
                'lot_size': 100,
                'limit_one_word_bar_unfilled': True,
                'force_flat_friday': True,
            },
            'cost_model': {
                'commission_rate': self.cfg.fees.commission_rate,
                'commission_cap': self.cfg.fees.commission_cap,
                'transfer_fee_rate': self.cfg.fees.transfer_fee_rate,
                'stamp_duty_rate': self.cfg.fees.stamp_duty_rate,
                'slippage_bps': self.cfg.fees.slippage_bps,
                'min_commission': self.cfg.fees.min_commission,
            },
            'asof_policy': {
                'candidate_meta_required': True,
                'asof_datetime_rule': 'D-1 15:00:00',
                'pool_size': self.cfg.experiment.candidate_size,
            },
            'data_coverage_summary': _doctor_summary(self.cfg, start, end),
        }
        (results_root / 'manifest.json').write_text(_json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        return results_root


def _safe_git_commit() -> str:
    try:
        out = subprocess.check_output(['git', 'rev-parse', 'HEAD'], stderr=subprocess.DEVNULL)
        return out.decode('utf-8').strip()
    except Exception:
        return 'unknown'


def _hash_configs(cfg: AppConfig) -> str:
    root = Path('configs')
    h = hashlib.sha256()
    if root.exists():
        for p in sorted(root.rglob('*.yaml')):
            try:
                h.update(p.read_bytes())
            except Exception:
                pass
    return h.hexdigest()


def _doctor_summary(cfg: AppConfig, start: str, end: str) -> dict:
    try:
        out = run_doctor(cfg, start, end)
        obj = _json.loads(out.read_text(encoding='utf-8'))
        checks = obj.get('checks', {})
        cov = checks.get('min5_coverage', {})
        return {
            'pairs_total': cov.get('pairs_total', 0),
            'pairs_covered': cov.get('pairs_covered', 0),
            'missing_days': len(checks.get('candidates', {}).get('missing_days', [])),
        }
    except Exception:
        return {}
