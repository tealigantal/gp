from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pandas as pd

from ..config import AppConfig
from ..engine.backtest import BacktestEngine
from ..policy.policy_store import PolicyStore, PolicySpec
from ..rankers.llm_ranker import rank as llm_rank
from ..storage import load_parquet


def _trade_dates(cfg: AppConfig, start: str, end: str) -> List[str]:
    cal = load_parquet(cfg.paths.data_root / 'raw' / 'trade_cal.parquet')
    if cal.empty:
        raise RuntimeError('trade_cal missing; run fetch first')
    return cal[(cal['trade_date'] >= start) & (cal['trade_date'] <= end)]['trade_date'].astype(str).tolist()


def _shift_weeks(cfg: AppConfig, end: str, weeks: int) -> str:
    # approximate by 5*weeks trading days
    cal = load_parquet(cfg.paths.data_root / 'raw' / 'trade_cal.parquet')
    arr = cal['trade_date'].astype(str).tolist()
    arr = [d for d in arr if d <= end]
    if len(arr) < 5 * weeks:
        return arr[0]
    return arr[-(5 * weeks)]


def tune(cfg: AppConfig, end: str, lookback_weeks: int, eval_weeks: int, templates: List[str], entries: List[str], exits: List[str], min_trades: int = 10, topk: int = 3) -> Path:
    lookback_start = _shift_weeks(cfg, end, lookback_weeks)
    store = PolicyStore(cfg)

    best = None
    best_key = None

    for tmpl in templates:
        # ensure llm-rank cache for each trading day
        days = _trade_dates(cfg, lookback_start, end)
        ranked_map: Dict[str, List[str]] = {}
        for d in days:
            df = llm_rank(cfg, d, tmpl, force=False, topk=topk)
            ranked_map[d] = df['ts_code'].astype(str).tolist()

        for entry in entries:
            for exit_id in exits:
                # Map entry/exit to strategy
                strat_name = 'time_entry_min5' if entry == 'baseline' else entry
                from ..cli import _load_strategy
                strat = _load_strategy(strat_name)
                # configure exit time (simple template)
                if hasattr(strat, 'params') and hasattr(strat.params, 'exit_time'):
                    strat.params.exit_time = '10:00:00'
                if hasattr(strat, 'params') and hasattr(strat.params, 'top_k'):
                    strat.params.top_k = topk

                engine = BacktestEngine(cfg)
                res = engine.run_weekly(lookback_start, end, strategies={strat_name: strat}, min_missing_threshold=0.1, ranked_map=ranked_map)  # type: ignore
                cmp_path = res / 'compare_strategies.csv'
                cmp_df = pd.read_csv(cmp_path)
                row = cmp_df[cmp_df['strategy'] == strat_name].iloc[0]
                n_tr = int(row['n_trades'])
                status = str(row['status'])
                win_rate = float(row['win_rate'])
                avg_pnl = float(row['avg_pnl'])
                max_dd = float(row['max_drawdown'])

                store.append_score({
                    'lookback_start': lookback_start,
                    'lookback_end': end,
                    'template': tmpl,
                    'entry': entry,
                    'exit': exit_id,
                    'n_trades': n_tr,
                    'win_rate': win_rate,
                    'avg_pnl': avg_pnl,
                    'max_drawdown': max_dd,
                    'status': status,
                })

                # Selection with min_trades filter
                if status == 'NO_SIGNAL' or n_tr < min_trades:
                    continue
                key = (win_rate, avg_pnl, -max_dd)
                if best is None or key > best_key:
                    best = (tmpl, entry, exit_id, n_tr, win_rate, avg_pnl, max_dd)
                    best_key = key

    if not best:
        raise RuntimeError('No valid policy met the minimum trades requirement; tune failed')

    tmpl, entry, exit_id, n_tr, win_rate, avg_pnl, max_dd = best
    spec = PolicySpec(
        as_of_date=end,
        lookback_start=lookback_start,
        lookback_end=end,
        ranker_template_id=tmpl,
        entry_strategy_id='time_entry_min5' if entry == 'baseline' else entry,
        exit_template_id=exit_id,
        topk=topk,
        target_pct=0.25,
        max_positions=1,
        score=win_rate,
        metrics={
            'win_rate': win_rate,
            'avg_pnl': avg_pnl,
            'max_drawdown': max_dd,
            'n_trades': n_tr,
        },
        notes='auto-selected by tune',
    )
    return store.save_current(spec)

