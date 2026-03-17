from __future__ import annotations

import json
from fastapi.testclient import TestClient
from gp_assistant.server.app import app
from gp_assistant.core.paths import store_dir


client = TestClient(app)


def _wr(path: str, obj: dict) -> None:
    p = store_dir() / "recommend"
    p.mkdir(parents=True, exist_ok=True)
    (p / path).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_recommend_v2_reads_persisted_v2_first():
    v2 = {
        "artifact_version": "v2",
        "run_id": "20250115",
        "as_of": "20250115",
        "degraded": False,
        "tradeable": True,
        "symbols": ["AAA000"],
        "themes": [],
        "items": [
            {"pick_id": "20250115:AAA000", "symbol": "AAA000", "entry_zone": [9.7, 9.9], "take_profit": [10.6], "reward_risk": 1.2, "execution_state": "waiting_pullback", "actionable": False}
        ],
    }
    _wr("20250115_v2.json", v2)
    r = client.get("/api/recommend_v2", params={"run_id": "20250115"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("artifact_version") == "v2"
    assert data.get("fallback_used") is False
    assert data.get("run_id") == "20250115"


def test_recommend_v2_fallback_from_v1_when_v2_missing():
    v1 = {
        "as_of": "20250116",
        "env": {"grade": "B"},
        "picks": [
            {"symbol": "BBB000", "champion": {"strategy": "s01", "score": 0.6}, "last_close": 10.0, "trade_plan": {"bands": {"S1": 9.7, "R1": 10.6}, "diagnostics": {"reward_risk": 0.6, "actionable": False, "execution_state": "observe_only", "setup_age": 2}}}
        ],
        "candidate_pool": [
            {"symbol": "BBB000", "liquidity": {"grade": "B"}, "indicators": {"atr_pct": 0.03}, "flags": {"reasons": []}},
        ],
        "debug": {"degraded": False},
        "tradeable": True,
    }
    _wr("20250116.json", v1)
    r = client.get("/api/recommend_v2", params={"run_id": "20250116"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("artifact_version") == "v2"
    assert data.get("fallback_used") is True
    assert data.get("run_id") == "20250116"

