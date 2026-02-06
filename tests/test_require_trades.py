import pandas as pd
from pathlib import Path
import types

from src.gpbt.config import AppConfig, Paths, Fees, UniverseCfg, BarsCfg, ExperimentCfg
from src.gpbt.cli import cmd_backtest


def make_cfg(tmp: Path) -> AppConfig:
    data = tmp / 'data'
    uni = tmp / 'universe'
    res = tmp / 'results'
    (data / 'bars' / 'daily').mkdir(parents=True, exist_ok=True)
    (data / 'raw').mkdir(parents=True, exist_ok=True)
    cfg = AppConfig(
        provider='local_files',
        paths=Paths(data_root=data, universe_root=uni, results_root=res),
        fees=Fees(),
        universe=UniverseCfg(),
        bars=BarsCfg(),
        experiment=ExperimentCfg(run_id='t2', require_trades=False)
    )
    return cfg


def fake_run_weekly(self, start, end, strategies, **kw):
    root = self.cfg.paths.results_root / f"run_{self.cfg.experiment.run_id}"
    root.mkdir(parents=True, exist_ok=True)
    (root / 'compare_strategies.csv').write_text(
        "strategy,n_trades,win_rate,total_return_net,max_drawdown_net,turnover,no_fill_buy,no_fill_sell,forced_flat_count,status\n"
        "s1,0,0.0,0.000,0.000,0.00,0,0,0,NO_SIGNAL\n",
        encoding='utf-8'
    )
    return root


def test_require_trades_flag(tmp_path, monkeypatch):
    from src.gpbt.engine.backtest import BacktestEngine
    monkeypatch.setattr(BacktestEngine, 'run_weekly', fake_run_weekly)
    cfg = make_cfg(tmp_path)
    # Should not raise when require_trades False
    cmd_backtest(cfg, '20260106', '20260106', ['baseline_daily'], require_trades=False)
    # Should raise when require_trades True
    import pytest
    with pytest.raises(RuntimeError):
        cmd_backtest(cfg, '20260106', '20260106', ['baseline_daily'], require_trades=True)

