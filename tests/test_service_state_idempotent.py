from __future__ import annotations

from pathlib import Path
import json

from src.service.pipeline import service_intraday


def test_service_intraday_idempotent(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # minimal layout
    (tmp_path / 'store' / 'recommend').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'store' / 'registry').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'universe').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'configs').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'configs' / 'config.yaml').write_text('initial_cash: 1000000\nmax_positions: 5\nvol_unit: shares\n', encoding='utf-8')
    (tmp_path / 'universe' / 'candidate_pool_20250106.csv').write_text('ts_code\n', encoding='utf-8')
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
    # run twice
    service_intraday('20250106')
    p1 = (tmp_path / 'results' / 'live_shadow' / '20250106' / 'order_log.csv').read_text(encoding='utf-8')
    service_intraday('20250106')
    p2 = (tmp_path / 'results' / 'live_shadow' / '20250106' / 'order_log.csv').read_text(encoding='utf-8')
    assert p1 == p2

