from __future__ import annotations

import json
from fastapi.testclient import TestClient
from gp_assistant.gateway.app import app
from gp_assistant.core.paths import store_dir


client = TestClient(app)


def _write_latest(payload: dict) -> None:
    p = store_dir() / "recommend"
    p.mkdir(parents=True, exist_ok=True)
    (p / "latest.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_pick_detail_returns_item():
    v1 = {
        "as_of": "20250115",
        "env": {"grade": "B"},
        "picks": [
            {
                "symbol": "CCC000",
                "champion": {"strategy": "s01", "score": 0.7},
                "last_close": 30.0,
                "trade_plan": {"bands": {"S1": 29.0, "R1": 31.5}, "diagnostics": {"reward_risk": 0.8, "actionable": False, "execution_state": "waiting_pullback", "setup_age": 3}},
            },
        ],
        "candidate_pool": [
            {"symbol": "CCC000", "liquidity": {"grade": "B"}, "indicators": {"atr_pct": 0.04}, "flags": {"reasons": ["ATR_HIGH_OBSERVE"]}},
        ],
        "debug": {"degraded": False},
        "tradeable": True,
    }
    _write_latest(v1)
    r = client.get("/api/pick", params={"symbol": "CCC000"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is True
    it = data.get("item")
    assert isinstance(it, dict)
    assert it.get("symbol") == "CCC000"
    assert "execution_state" in it and "alpha_score" in it
