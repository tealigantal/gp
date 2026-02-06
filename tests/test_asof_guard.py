import json
from pathlib import Path

import pandas as pd

from src.gpbt.config import AppConfig, Paths, Fees, UniverseCfg, BarsCfg, ExperimentCfg
from src.gpbt.doctor import run_doctor


def make_cfg(tmp: Path) -> AppConfig:
    data = tmp / 'data'
    uni = tmp / 'universe'
    res = tmp / 'results'
    data.mkdir(parents=True, exist_ok=True)
    (data / 'raw').mkdir(parents=True, exist_ok=True)
    (data / 'bars' / 'daily').mkdir(parents=True, exist_ok=True)
    cfg = AppConfig(
        provider='local_files',
        paths=Paths(data_root=data, universe_root=uni, results_root=res),
        fees=Fees(),
        universe=UniverseCfg(),
        bars=BarsCfg(),
        experiment=ExperimentCfg(run_id='t1')
    )
    return cfg


def test_doctor_asof_after_open(tmp_path: Path):
    cfg = make_cfg(tmp_path)
    # trade calendar
    cal = pd.DataFrame({'trade_date': ['20260106']})
    cal.to_parquet(cfg.paths.data_root / 'raw' / 'trade_cal.parquet', index=False)
    # candidate pool and meta
    cfg.paths.universe_root.mkdir(parents=True, exist_ok=True)
    (cfg.paths.universe_root / 'candidate_pool_20260106.csv').write_text('ts_code\n000001.SZ\n', encoding='utf-8')
    meta = {
        'trade_date': '2026-01-06',
        'asof_datetime': '2026-01-06 10:00:00',  # after open -> error
        'selector_name': 'test',
        'selector_params': {},
        'filters_applied': {}
    }
    (cfg.paths.universe_root / 'candidate_pool_20260106.meta.json').write_text(json.dumps(meta), encoding='utf-8')

    out = run_doctor(cfg, '20260106', '20260106')
    obj = json.loads(out.read_text(encoding='utf-8'))
    assert 'candidates_meta' in obj['checks']
    assert obj.get('status') == 'ERROR'

