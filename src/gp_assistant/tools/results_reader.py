from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class StrategySummary:
    strategy: str
    n_trades: int
    win_rate: float
    avg_pnl: float
    avg_win: float
    avg_loss: float
    payoff_ratio: float
    total_return: float
    max_drawdown: float
    no_fill_buy: int
    no_fill_sell: int
    forced_flat_delayed: int
    status: str


def _find_latest_run(results_root: Path) -> Optional[Path]:
    runs = [p for p in results_root.glob('run_*') if p.is_dir()]
    if not runs:
        return None
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0]


def read_compare(run_dir: Path) -> List[StrategySummary]:
    cmp = run_dir / 'compare_strategies.csv'
    out: List[StrategySummary] = []
    if not cmp.exists():
        return out
    with open(cmp, 'r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                out.append(StrategySummary(
                    strategy=row['strategy'],
                    n_trades=int(float(row['n_trades'])),
                    win_rate=float(row['win_rate']),
                    avg_pnl=float(row['avg_pnl']),
                    avg_win=float(row['avg_win']),
                    avg_loss=float(row['avg_loss']),
                    payoff_ratio=float(row['payoff_ratio']),
                    total_return=float(row['total_return']),
                    max_drawdown=float(row['max_drawdown']),
                    no_fill_buy=int(float(row['no_fill_buy'])),
                    no_fill_sell=int(float(row['no_fill_sell'])),
                    forced_flat_delayed=int(float(row['forced_flat_delayed'])),
                    status=row.get('status', 'OK'),
                ))
            except Exception:
                continue
    return out


def summarize_run(results_root: Path, run_id: Optional[str] = None) -> str:
    if run_id:
        run_dir = results_root / f'run_{run_id}'
    else:
        latest = _find_latest_run(results_root)
        if latest is None:
            return "No run_* found under results/"
        run_dir = latest
    if not run_dir.exists():
        return f"Run not found: {run_dir}"
    rows = read_compare(run_dir)
    if not rows:
        return f"No compare_strategies.csv in {run_dir}"
    rows.sort(key=lambda x: (x.n_trades, x.win_rate, x.total_return), reverse=True)
    lines = [f"Results at {run_dir} (top by trades,win,ret):"]
    for s in rows:
        lines.append(
            f"- {s.strategy}: trades={s.n_trades}, win={s.win_rate:.1%}, ret={s.total_return:.2%}, dd={s.max_drawdown:.2%}, status={s.status}"
        )
    return "\n".join(lines)

