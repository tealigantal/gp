from __future__ import annotations

from gp_assistant.recommend.calibration import calibrate_item_scores


def test_calibration_execution_actionable_higher():
    base_item = {
        "champion": {"score": 0.8},
        "trade_plan": {"diagnostics": {"execution_state": "observe_only", "reward_risk": 0.5}},
        "liquidity_grade": "A",
    }
    s_obs = calibrate_item_scores(base_item, degraded=False)
    act_item = {
        "champion": {"score": 0.8},
        "trade_plan": {"diagnostics": {"execution_state": "actionable", "reward_risk": 0.5}},
        "liquidity_grade": "A",
    }
    s_act = calibrate_item_scores(act_item, degraded=False)
    assert 0.0 <= s_obs["execution_score"] <= 1.0
    assert 0.0 <= s_act["execution_score"] <= 1.0
    assert s_act["execution_score"] > s_obs["execution_score"]

