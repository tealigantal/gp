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


def test_compare_returns_ranking_and_winner(tmp_path):
    v1 = {
        "as_of": "20250115",
        "env": {"grade": "B"},
        "picks": [
            {
                "symbol": "AAA000",
                "champion": {"strategy": "s01", "score": 0.8},
                "last_close": 10.0,
                "trade_plan": {"bands": {"S1": 9.7, "R1": 10.6}, "diagnostics": {"reward_risk": 1.2, "actionable": False, "execution_state": "waiting_pullback", "setup_age": 1}},
            },
            {
                "symbol": "BBB000",
                "champion": {"strategy": "s01", "score": 0.9},
                "last_close": 20.0,
                "trade_plan": {"bands": {"S1": 19.5, "R1": 21.0}, "diagnostics": {"reward_risk": 1.5, "actionable": True, "execution_state": "actionable", "setup_age": 1}},
            },
        ],
        "candidate_pool": [
            {"symbol": "AAA000", "liquidity": {"grade": "B"}, "indicators": {"atr_pct": 0.03}, "flags": {"reasons": []}},
            {"symbol": "BBB000", "liquidity": {"grade": "A"}, "indicators": {"atr_pct": 0.02}, "flags": {"reasons": []}},
        ],
        "debug": {"degraded": False},
        "tradeable": True,
    }
    _write_latest(v1)
    body = {"symbols": ["AAA000", "BBB000"]}
    r = client.post("/api/compare", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is True
    assert data.get("winner_symbol") in {"AAA000", "BBB000"}
    assert isinstance(data.get("ranking"), list) and len(data.get("ranking")) == 2
