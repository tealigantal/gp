from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.service.pipeline import service_preopen, service_intraday, service_close


def test_service_pipeline_smoke(tmp_path: Path, monkeypatch):
    # switch CWD to tmp
    monkeypatch.chdir(tmp_path)
    # prepare dirs
    (tmp_path / 'store' / 'recommend').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'store' / 'registry').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'universe').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'configs').mkdir(parents=True, exist_ok=True)
    # config
    (tmp_path / 'configs' / 'config.yaml').write_text('initial_cash: 1000000\nmax_positions: 5\nvol_unit: shares\n', encoding='utf-8')
    # candidate pool with one symbol
    pd.DataFrame({"ts_code": ["000001.SZ"]}).to_csv(tmp_path / 'universe' / 'candidate_pool_20250106.csv', index=False)
    # champion registry
    champ = {
        "champion_id": "demo",
        "selected_at": "20250103",
        "seed": 42,
        "git_commit": None,
        "strategy_type": "baseline",
        "params": {"entry_time": "09:50:00", "topk": 1, "lot_shares": 100},
        "params_hash": "x",
        "scenario": "base",
        "robust": {"robust_sharpe_p05": 0.0},
        "constraints": {},
        "warnings": {},
    }
    (tmp_path / 'store' / 'registry' / 'champion.json').write_text(json.dumps(champ), encoding='utf-8')
    # run pipeline
    service_preopen('20250106', topk=1)
    service_intraday('20250106')
    service_close('20250106')
    # asserts
    assert (tmp_path / 'store' / 'recommend' / '20250106.json').exists()
    assert (tmp_path / 'store' / 'recommend' / 'latest.json').exists()
    assert (tmp_path / 'results' / 'live_shadow' / '20250106' / 'order_log.csv').exists()
    assert (tmp_path / 'results' / 'live_shadow' / '20250106' / 'equity.csv').exists()
    assert (tmp_path / 'results' / 'live_shadow' / '20250106' / 'metrics.json').exists()

