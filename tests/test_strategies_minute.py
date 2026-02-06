from __future__ import annotations

from pathlib import Path
import json
import pandas as pd

from src.gpbt.config import AppConfig, Paths, Fees, UniverseCfg, BarsCfg, ExperimentCfg
from src.gpbt.engine.backtest import BacktestEngine
from src.gpbt.strategy.time_entry_min5 import TimeEntryMin5, TimeEntryParams
from src.gpbt.strategy.open_range_breakout import OpenRangeBreakout, ORBParams
from src.gpbt.strategy.vwap_reclaim_pullback import VWAPReclaimPullback, VWAPParams
from src.gpbt.strategy.baseline_daily import BaselineDaily, BaselineDailyParams
from tests.fixtures.min_data import seed_min_dataset


def make_cfg(tmp: Path, run_id: str) -> AppConfig:
    paths = seed_min_dataset(tmp)
    return AppConfig(
        provider='local_files',
        paths=Paths(data_root=paths['data_root'], universe_root=paths['universe_root'], results_root=paths['results_root']),
        fees=Fees(),
        universe=UniverseCfg(),
        bars=BarsCfg(),
        experiment=ExperimentCfg(run_id=run_id, initial_cash=100000.0)
    )


def test_strategy_smoke_all(tmp_path: Path):
    cfg = make_cfg(tmp_path, run_id='smoke')
    eng = BacktestEngine(cfg)
    strats = {
        'time_entry_min5': TimeEntryMin5(TimeEntryParams(entry_time='10:00:00', exit_time='10:00:00', top_k=1, max_positions=1)),
        'open_range_breakout': OpenRangeBreakout(ORBParams(range_end_time='10:00:00', breakout_bps=0, exit_time='10:00:00', top_k=1, max_positions=1)),
        'vwap_reclaim_pullback': VWAPReclaimPullback(VWAPParams(start_time='10:00:00', dip_bps=0, exit_time='10:00:00', top_k=1, max_positions=1)),
        'baseline_daily': BaselineDaily(BaselineDailyParams(buy_top_k=1, per_stock_cash=0.5)),
    }
    out = eng.run_weekly('20260106', '20260107', strategies=strats)
    assert (out / 'compare_strategies.csv').exists()
    cmp = pd.read_csv(out / 'compare_strategies.csv')
    # Each strategy should have at least 1 trade on this fixture
    by = {r['strategy']: int(r['n_trades']) for _, r in cmp.iterrows()}
    assert by.get('time_entry_min5', 0) >= 1
    assert by.get('open_range_breakout', 0) >= 1
    assert by.get('vwap_reclaim_pullback', 0) >= 1
    assert by.get('baseline_daily', 0) >= 1


def test_no_future_function_fill_policy(tmp_path: Path):
    cfg = make_cfg(tmp_path, run_id='policy')
    eng = BacktestEngine(cfg)
    strats = {
        'time_entry_min5': TimeEntryMin5(TimeEntryParams(entry_time='10:00:00', exit_time='10:00:00', top_k=1, max_positions=1)),
    }
    out = eng.run_weekly('20260106', '20260107', strategies=strats)
    events = []
    for line in (out / 'events.jsonl').read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    buy_times = [e['time'] for e in events if e.get('event_type') == 'fill' and e.get('side') == 'buy']
    # Ensure first buy happens at 10:05 (next bar open) not 10:00
    assert any('10:05:00' in t for t in buy_times)
    assert not any('10:00:00' in t and '2026-01-06' in t for t in buy_times)


def test_tplus1(tmp_path: Path):
    cfg = make_cfg(tmp_path, run_id='tplus1')
    eng = BacktestEngine(cfg)
    strats = {
        'open_range_breakout': OpenRangeBreakout(ORBParams(range_end_time='10:00:00', breakout_bps=0, exit_time='10:00:00', top_k=1, max_positions=1)),
    }
    out = eng.run_weekly('20260106', '20260107', strategies=strats)
    events = [json.loads(l) for l in (out / 'events.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    days_by_code = {}
    for e in events:
        d = e['time'].split(' ')[0]
        key = (e.get('code'), d)
        days_by_code.setdefault(key, set()).add(e.get('side'))
    # No same-day buy and sell
    assert all(not ({'buy','sell'} <= s) for s in days_by_code.values())


def test_lot_size_100(tmp_path: Path):
    cfg = make_cfg(tmp_path, run_id='lot100')
    eng = BacktestEngine(cfg)
    strats = {'time_entry_min5': TimeEntryMin5(TimeEntryParams(entry_time='10:00:00', exit_time='10:00:00', top_k=1, max_positions=1))}
    out = eng.run_weekly('20260106', '20260107', strategies=strats)
    # find trades.csv
    trg = out / 'time_entry_min5' / 'trades.csv'
    rows = (trg.read_text(encoding='utf-8').strip().splitlines())[1:]
    shares = [int(r.split(',')[5]) for r in rows]
    assert all(s % 100 == 0 for s in shares)

