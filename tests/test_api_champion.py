from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from gp_assistant.gateway.app import app


def test_api_champion(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'store' / 'registry').mkdir(parents=True, exist_ok=True)
    sample = {
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
    (tmp_path / 'store' / 'registry' / 'champion.json').write_text(json.dumps(sample), encoding='utf-8')
    client = TestClient(app)
    r = client.get('/api/champion')
    assert r.status_code == 200
    data = r.json()
    assert data.get('strategy_type') == 'baseline'

