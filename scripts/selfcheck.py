from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path


def run_backtest_with_fixture(tmp: Path) -> None:
    # Programmatic: use BacktestEngine to avoid dependency on external network
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from tests.fixtures.min_data import seed_min_dataset  # type: ignore
    from src.gpbt.config import AppConfig, Paths, Fees, UniverseCfg, BarsCfg, ExperimentCfg  # type: ignore
    from src.gpbt.engine.backtest import BacktestEngine  # type: ignore
    from src.gpbt.strategy.time_entry_min5 import TimeEntryMin5, TimeEntryParams  # type: ignore
    from src.gpbt.strategy.open_range_breakout import OpenRangeBreakout, ORBParams  # type: ignore
    from src.gpbt.strategy.vwap_reclaim_pullback import VWAPReclaimPullback, VWAPParams  # type: ignore
    from src.gpbt.strategy.baseline_daily import BaselineDaily, BaselineDailyParams  # type: ignore

    paths = seed_min_dataset(tmp)
    cfg = AppConfig(
        provider='local_files',
        paths=Paths(data_root=paths['data_root'], universe_root=paths['universe_root'], results_root=paths['results_root']),
        fees=Fees(),
        universe=UniverseCfg(),
        bars=BarsCfg(),
        experiment=ExperimentCfg(run_id='selfcheck')
    )
    eng = BacktestEngine(cfg)
    strats = {
        'time_entry_min5': TimeEntryMin5(TimeEntryParams(entry_time='10:00:00', exit_time='10:00:00', top_k=1, max_positions=1)),
        'open_range_breakout': OpenRangeBreakout(ORBParams(range_end_time='10:00:00', breakout_bps=0, exit_time='10:00:00', top_k=1, max_positions=1)),
        'vwap_reclaim_pullback': VWAPReclaimPullback(VWAPParams(start_time='10:00:00', dip_bps=0, exit_time='10:00:00', top_k=1, max_positions=1)),
        'baseline_daily': BaselineDaily(BaselineDailyParams(buy_top_k=1, per_stock_cash=0.5)),
    }
    out = eng.run_weekly('20260106', '20260107', strategies=strats)
    if not (out / 'compare_strategies.csv').exists():
        raise RuntimeError('compare_strategies.csv not found in selfcheck')


def run_assistant_once(tmp: Path) -> None:
    # Prepare configs for mock provider and run once
    (tmp / 'configs').mkdir(parents=True, exist_ok=True)
    (tmp / 'configs' / 'assistant.yaml').write_text('workspace_root: .\n', encoding='utf-8')
    (tmp / 'configs' / 'llm.yaml').write_text('provider: mock\njson_mode: true\n', encoding='utf-8')
    (tmp / 'configs' / 'config.yaml').write_text(
        'provider: local_files\n'
        'data_root: data\n'
        'universe_root: universe\n'
        'results_root: results\n'
        'universe:\n  min_list_days: 1\n  exclude_st: false\n  min_amount: 1.0\n  min_vol: 1\n'
        'bars:\n  daily_adj: qfq\n  min_freq: 5min\n'
        'fees:\n  commission_rate: 0.0003\n  commission_cap: 0.0013\n  transfer_fee_rate: 0.00001\n  stamp_duty_rate: 0.0005\n  slippage_bps: 3\n  min_commission: 0\n'
        'experiment:\n  candidate_size: 20\n  initial_cash: 1000000\n  run_id: default\n',
        encoding='utf-8'
    )
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, str(repo_root / 'assistant.py'), 'chat', '--once', '荐股']
    p = subprocess.run(cmd, cwd=str(tmp), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError('assistant once failed: ' + (p.stderr or p.stdout))
    if '荐股 Top' not in (p.stdout or ''):
        raise RuntimeError('assistant output missing TopK')
    # Switch to rule fallback by setting deepseek without proxy and no key
    (tmp / 'configs' / 'llm.yaml').write_text('provider: deepseek\nbase_url: http://127.0.0.1:65535/v1\njson_mode: true\n', encoding='utf-8')
    p2 = subprocess.run(cmd, cwd=str(tmp), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p2.returncode != 0:
        raise RuntimeError('assistant once (rule fallback) failed: ' + (p2.stderr or p2.stdout))
    if '荐股 Top' not in (p2.stdout or ''):
        raise RuntimeError('assistant output missing TopK (rule)')


def main() -> int:
    tmp = Path('selfcheck_tmp')
    if tmp.exists():
        # Clean up previous
        import shutil
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    run_backtest_with_fixture(tmp)
    run_assistant_once(tmp)
    print('Selfcheck OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
