from __future__ import annotations

from gp_assistant.recommend.contracts import build_v2_from_v1
from gp_assistant.recommend.validators import validate_pick_artifact_v2


def test_v2_artifact_validator_happy_path():
    v1 = {
        "as_of": "20250115",
        "env": {"grade": "B"},
        "picks": [
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "theme": "白酒",
                "champion": {"strategy": "s01", "score": 0.9},
                "last_close": 100.0,
                "trade_plan": {
                    "bands": {"S1": 98.0, "S2": 99.0, "R1": 104.0, "R2": 106.0},
                    "entry": [98.0, 99.0],
                    "take": [104.0, 106.0],
                    "invalidation": ["close_below_S1"],
                    "diagnostics": {"reward_risk": 1.5, "actionable": True, "execution_state": "actionable", "setup_age": 2},
                },
            }
        ],
        "candidate_pool": [
            {"symbol": "600519", "liquidity": {"grade": "A"}, "indicators": {"atr_pct": 0.03}, "flags": {"reasons": []}},
        ],
        "debug": {"degraded": False},
        "tradeable": True,
        "message": None,
    }
    art = build_v2_from_v1(v1)
    obj = {
        "run_id": art.run_id,
        "as_of": art.as_of,
        "snapshot_id": art.snapshot_id,
        "market_regime": art.market_regime,
        "degraded": art.degraded,
        "tradeable": art.tradeable,
        "reason": art.reason,
        "risk_profile": art.risk_profile,
        "universe_name": art.universe_name,
        "symbols": art.symbols,
        "themes": art.themes,
        "items": [it.__dict__ for it in art.items],
    }
    ok, errs, fixed = validate_pick_artifact_v2(obj)
    assert ok, f"unexpected errors: {errs}"
    it = fixed["items"][0]
    assert it["pick_id"] and it["symbol"] == "600519"
    assert isinstance(it["take_profit"], list) and len(it["take_profit"]) >= 1

