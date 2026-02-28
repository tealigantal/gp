from __future__ import annotations

import json
import threading
from pathlib import Path

from src.service.pipeline import service_preopen, service_publish


def test_publish_atomic_concurrent(tmp_path: Path, monkeypatch):
    # switch CWD
    monkeypatch.chdir(tmp_path)
    # prepare dirs
    (tmp_path / 'store' / 'recommend').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'store' / 'registry').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'universe').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'configs').mkdir(parents=True, exist_ok=True)
    # minimal config
    (tmp_path / 'configs' / 'config.yaml').write_text('initial_cash: 1000000\nmax_positions: 5\n', encoding='utf-8')
    # candidate pool
    (tmp_path / 'universe' / 'candidate_pool_20250106.csv').write_text('ts_code\n000001.SZ\n', encoding='utf-8')
    # champion registry (minimal fields used by preopen)
    champ = {
        "strategy_type": "baseline",
        "params_hash": "x",
        "scenario": "base",
        "robust": {"robust_sharpe_p05": 0.0},
    }
    (tmp_path / 'store' / 'registry' / 'champion.json').write_text(json.dumps(champ), encoding='utf-8')

    # pre-generate date file
    service_preopen('20250106', topk=1)

    # concurrently publish same date many times
    def worker():
        for _ in range(10):
            service_publish('20250106')

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start(); t1.join(); t2.join()

    # latest must be valid JSON and have stable schema fields
    latest = json.loads((tmp_path / 'store' / 'recommend' / 'latest.json').read_text(encoding='utf-8'))
    assert isinstance(latest, dict)
    assert isinstance(latest.get('picks'), list)
    assert latest.get('stage') in {'preopen', 'intraday', 'close'}
    # required fields enforced by pipeline
    assert isinstance(latest.get('as_of'), str)
    assert isinstance(latest.get('as_of_ts'), str)

