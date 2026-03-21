from __future__ import annotations

from gp_assistant.recommend.calibration import calibrate_item_scores


def test_calibration_execution_actionable_higher():
    # V2 item with internal score basis
    base_item = {
        "_score_inputs": {"champion_score_raw": 0.8},
        "execution_state": "observe_only",
        "reward_risk": 0.5,
        "liquidity_grade": "A",
    }
    s_obs = calibrate_item_scores(base_item, degraded=False)
    act_item = {
        "_score_inputs": {"champion_score_raw": 0.8},
        "execution_state": "actionable",
        "reward_risk": 0.5,
        "liquidity_grade": "A",
    }
    s_act = calibrate_item_scores(act_item, degraded=False)
    assert 0.0 <= s_obs["execution_score"] <= 1.0
    assert 0.0 <= s_act["execution_score"] <= 1.0
    assert s_act["execution_score"] > s_obs["execution_score"]


def test_calibration_rr_orders_actionable_items():
    a_low = {"execution_state": "actionable", "reward_risk": 0.2, "liquidity_grade": "A"}
    a_high = {"execution_state": "actionable", "reward_risk": 1.6, "liquidity_grade": "A"}
    s_low = calibrate_item_scores(a_low, degraded=False)
    s_high = calibrate_item_scores(a_high, degraded=False)
    assert s_high["execution_score"] > s_low["execution_score"], (s_low, s_high)
