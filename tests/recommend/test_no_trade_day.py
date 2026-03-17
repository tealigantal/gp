from __future__ import annotations

from gp_assistant.recommend.calibration import compute_no_trade_gate


def test_no_trade_day_gate_triggers_when_all_observe_only():
    art = {
        "items": [
            {"actionable": False, "execution_score": 0.2, "alpha_score": 0.4, "reliability_score": 0.8},
            {"actionable": False, "execution_score": 0.3, "alpha_score": 0.3, "reliability_score": 0.7},
        ]
    }
    gate = compute_no_trade_gate(art)
    assert gate.get("tradeable") is False
    assert isinstance(gate.get("reason"), str)

