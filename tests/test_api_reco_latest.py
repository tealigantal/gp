from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from gp_assistant.gateway.app import app
from src.gp_assistant.core.paths import store_dir


def test_api_reco_latest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'store' / 'recommend').mkdir(parents=True, exist_ok=True)
    latest = {
        "as_of": "2025-01-06 09:20:00",
        "timezone": "Asia/Shanghai",
        "tradeable": True,
        "message": "preopen",
        "disclaimer": "",
        "stage": "preopen",
        "picks": [],
        "debug": {"mode": "service", "degraded": False, "reasons": []},
    }
    (tmp_path / 'store' / 'recommend' / 'latest.json').write_text(json.dumps(latest), encoding='utf-8')
    client = TestClient(app)
    r = client.get('/api/reco/latest')
    assert r.status_code == 200
    data = r.json()
    assert 'as_of' in data and 'picks' in data and 'stage' in data

