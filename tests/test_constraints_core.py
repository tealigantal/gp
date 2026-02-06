from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from src.gpbt.config import AppConfig, Paths, Fees, UniverseCfg, BarsCfg, ExperimentCfg
from src.gpbt.engine.backtest import BacktestEngine
from src.gpbt.strategy.time_entry_min5 import TimeEntryMin5, TimeEntryParams
from src.gpbt.strategy.open_range_breakout import OpenRangeBreakout, ORBParams
from src.gpbt.strategy.vwap_reclaim_pullback import VWAPReclaimPullback, VWAPParams
from src.gpbt.strategy.baseline_daily import BaselineDaily, BaselineDailyParams
from tests.fixtures.min_data import seed_min_dataset


def _make_cfg(tmp: Path, run_id: str) -> AppConfig:
    paths = seed_min_dataset(tmp)
    return AppConfig(
        provider='local_files',
        paths=Paths(data_root=paths['data_root'], universe_root=paths['universe_root'], results_root=paths['results_root']),
        fees=Fees(),
        universe=UniverseCfg(),
        bars=BarsCfg(),
        experiment=ExperimentCfg(run_id=run_id, initial_cash=100000.0)
    )


def test_fill_policy_close_to_next_open(tmp_path: Path):
    cfg = _make_cfg(tmp_path, 'fpo')
    eng = BacktestEngine(cfg)
    out = eng.run_weekly('20260106', '20260107', strategies={
        'time_entry_min5': TimeEntryMin5(TimeEntryParams(entry_time='10:00:00', exit_time='10:00:00', top_k=1, max_positions=1)),
    })
    events = [json.loads(x) for x in (out / 'events.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    # Confirm that buy fills happen at the next bar open after 10:00:00 signal confirmation
    buys = [e for e in events if e.get('event_type') == 'fill' and e.get('side') == 'buy']
    assert any('10:05:00' in e['time'] for e in buys)
    assert not any('10:00:00' in e['time'] and 'buy' == e.get('side') for e in buys)


def test_tplus1_block(tmp_path: Path):
    cfg = _make_cfg(tmp_path, 't1')
    eng = BacktestEngine(cfg)
    out = eng.run_weekly('20260106', '20260107', strategies={'open_range_breakout': OpenRangeBreakout(ORBParams(range_end_time='10:00:00', breakout_bps=0, exit_time='10:00:00', top_k=1, max_positions=1))})
    events = [json.loads(x) for x in (out / 'events.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    by_day = {}
    for e in events:
        d = e['time'].split(' ')[0]
        by_day.setdefault((e.get('code'), d), set()).add(e.get('side'))
    assert all(not ({'buy','sell'} <= v) for v in by_day.values())


def test_lot_size_100(tmp_path: Path):
    cfg = _make_cfg(tmp_path, 'lot')
    eng = BacktestEngine(cfg)
    out = eng.run_weekly('20260106', '20260107', strategies={'time_entry_min5': TimeEntryMin5(TimeEntryParams(entry_time='10:00:00', exit_time='10:00:00', top_k=1, max_positions=1))})
    rows = (out / 'time_entry_min5' / 'trades.csv').read_text(encoding='utf-8').strip().splitlines()[1:]
    shares = [int(r.split(',')[5]) for r in rows]
    assert all(s % 100 == 0 for s in shares)


def test_minute_strategies_trigger(tmp_path: Path):
    cfg = _make_cfg(tmp_path, 'trg')
    eng = BacktestEngine(cfg)
    out = eng.run_weekly('20260106', '20260107', strategies={
        'open_range_breakout': OpenRangeBreakout(ORBParams(range_end_time='10:00:00', breakout_bps=0, exit_time='10:00:00', top_k=1, max_positions=1)),
        'vwap_reclaim_pullback': VWAPReclaimPullback(VWAPParams(start_time='10:00:00', dip_bps=0, exit_time='10:00:00', top_k=1, max_positions=1)),
    })
    cmp = pd.read_csv(out / 'compare_strategies.csv')
    by = {r['strategy']: int(r['n_trades']) for _, r in cmp.iterrows()}
    assert by.get('open_range_breakout', 0) >= 1
    assert by.get('vwap_reclaim_pullback', 0) >= 1

