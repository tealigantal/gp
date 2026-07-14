from __future__ import annotations

from pathlib import Path

from gp_assistant.book.daybook import _map_pick
from gp_assistant.decision_engine.adaptive_policy import select_candidates
from gp_assistant.evaluation_engine.calibration import calibration_report
from gp_assistant.evaluation_engine import historical_replay
from gp_assistant.market_memory.retrieval import retrieve_similar_events
from gp_assistant.market_memory.store import make_market_event, upsert_market_event
from gp_assistant.probability_engine.engine import infer_probability


def _event(symbol: str, *, as_of: str, signal_type: str, value: float, ret3: float, regime: str = "B"):
    vector = {
        "trend_strength": value,
        "pullback_quality": value,
        "volume_confirmation": value,
        "atr_pct": value,
        "extension_pct": value,
        "support_distance_pct": value,
        "liquidity_score": value,
        "market_regime_score": value,
        "industry_strength_score": value,
        "price_position_score": value,
    }
    return make_market_event(
        as_of=as_of,
        symbol=symbol,
        signal_type=signal_type,
        feature_vector=vector,
        features={"close": 10.0, "volume_ratio": 1.2, "atr_pct": 0.03},
        market_context={"market_regime": regime},
        outcome={
            "complete": True,
            "outcome_available_trading_day": "2024-01-08",
            "return_1d": ret3 / 2,
            "return_3d": ret3,
            "return_5d": ret3,
            "max_drawdown": min(0.0, ret3),
            "stop_hit": ret3 < -0.03,
            "success": ret3 > 0,
            "failure_modes": ["negative_3d_return"] if ret3 < 0 else [],
        },
        data_provenance={"source": "test"},
    )


def test_similarity_retrieval_uses_vector_distance_not_label(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))
    current = _event("000001", as_of="2024-02-01", signal_type="breakout_pullback", value=0.10, ret3=0.0)
    same_label_far = _event("000002", as_of="2024-01-01", signal_type="breakout_pullback", value=1.00, ret3=0.05)
    different_label_close = _event("000003", as_of="2024-01-02", signal_type="structure_watch", value=0.11, ret3=-0.01)
    upsert_market_event(same_label_far)
    upsert_market_event(different_label_close)

    result = retrieve_similar_events(current, as_of="2024-02-01", k=2)

    assert result["retrieval_method"] == "normalized_feature_vector_distance"
    assert result["cases"][0]["symbol"] == "000003"
    assert result["cases"][0]["vector_similarity"] > result["cases"][1]["vector_similarity"]


def test_probability_outputs_evidence_block_with_uncertainty():
    retrieval = {
        "retrieval_method": "normalized_feature_vector_distance",
        "pool_size": 3,
        "mean_similarity": 0.82,
        "prior_summary": {
            "global": {"sample_size": 3, "up_probability_3d": 2 / 3, "expected_return_3d": 0.02},
            "signal": {"sample_size": 2, "up_probability_3d": 0.5, "expected_return_3d": 0.01},
            "regime": {"sample_size": 3, "up_probability_3d": 2 / 3, "expected_return_3d": 0.02},
        },
        "cases": [
            {"similarity": 0.9, "signal_type": "breakout", "market_context": {"market_regime": "B"}, "outcome": {"return_1d": 0.01, "return_3d": 0.04, "max_drawdown": -0.01, "stop_hit": False}},
            {"similarity": 0.8, "signal_type": "breakout", "market_context": {"market_regime": "B"}, "outcome": {"return_1d": -0.01, "return_3d": -0.02, "max_drawdown": -0.04, "stop_hit": True, "failure_modes": ["drawdown_stop_like"]}},
        ],
    }
    output = infer_probability(current_event={"signal_type": "breakout", "market_context": {"market_regime": "B"}}, retrieval=retrieval)

    evidence = output["evidence"]
    assert 0.0 <= output["up_probability_3d"] <= 1.0
    assert evidence["sample_size"] == 2
    assert evidence["effective_sample_size"] > 1
    assert evidence["mean_similarity"] == 0.82
    assert evidence["pool_size"] == 3
    assert evidence["priors"]["source"] == "market_memory_pool"
    assert evidence["major_failure_modes"][0]["mode"] == "drawdown_stop_like"
    assert "uncertainty" in output


def test_adaptive_selection_owns_topk_without_llm_promotion():
    ranked = [
        {"symbol": "000001", "probability": {"up_probability_3d": 0.7, "expected_return_3d": 0.03, "evidence": {"effective_sample_size": 60}}, "risk": {"drawdown_probability": 0.1}, "ranking": {"ranking_score": 0.01}},
        {"symbol": "000002", "probability": {"up_probability_3d": 0.8, "expected_return_3d": 0.04, "evidence": {"effective_sample_size": 60}}, "risk": {"drawdown_probability": 0.1}, "ranking": {"ranking_score": 0.005}},
    ]

    result = select_candidates(ranked, topk=1, market_context={"grade": "B"})

    assert result["final_decision"] == "recommend"
    assert result["selected_symbols"] == [result["adaptive_candidates"][0]["symbol"]]
    assert result["validator_result"]["policy"] == "adaptive_policy_single_path"


def test_pipeline_does_not_import_or_call_risk_committee():
    source = Path("src/gp_assistant/decision_engine/pipeline.py").read_text(encoding="utf-8")

    assert "run_risk_committee" not in source
    assert "from .risk_committee" not in source


def test_calibration_report_includes_brier_and_effective_sample_buckets():
    report = calibration_report(
        [
            {"probability": 0.7, "success": True, "effective_sample_size": 12, "uncertainty": 0.1},
            {"probability": 0.6, "success": False, "effective_sample_size": 90, "uncertainty": 0.05},
        ],
        buckets=5,
    )

    assert report["sample_size"] == 2
    assert report["brier_score"] > 0
    assert len(report["buckets"]) == 5
    assert {row["bucket"] for row in report["effective_sample_buckets"]} == {"lt_10", "10_30", "30_80", "gte_80"}


def test_daybook_mapping_carries_market_memory_evidence():
    item = {
        "symbol": "000001",
        "signal_type": "breakout_pullback",
        "signal": {"signal_type": "breakout_pullback", "feature_vector": {"trend_strength": 0.8}},
        "probability": {"up_probability_3d": 0.68, "expected_return_3d": 0.031, "confidence": 0.7, "evidence": {"sample_size": 326, "effective_sample_size": 87, "mean_similarity": 0.82}},
        "risk": {"execution_quality": 0.75, "risk_flags": [], "entry": {"price": 10.0}, "stop": {"price": 9.5}, "take_profit": {"targets": [10.8]}},
        "ranking": {"ranking_score": 0.008},
        "adaptive_policy": {
            "adaptive_score": 0.61,
            "calibrated_probability": 0.59,
            "recommendation_strength": "normal",
            "action": "ENTRY",
            "feature_coverage": 0.8,
            "expert_scores": {"signal": 0.7},
            "expert_contributions": {"signal": 0.11},
            "missing_features": ["signal.features.support"],
        },
        "historical_cases": [{"symbol": "000002", "similarity": 0.91}],
        "trade_plan": {"entry": {"price": 10.0}, "stop": {"price": 9.5}, "take_profit": {"targets": [10.8]}, "diagnostics": {"reward_risk": 2.0, "execution_state": "actionable", "actionable": True}},
        "decision_context_snapshot_id": "dcs_test",
    }

    pick = _map_pick(1, item)

    assert pick.strategy_id == "breakout_pullback"
    assert pick.probability["up_probability_3d"] == 0.68
    assert pick.historical_cases[0]["symbol"] == "000002"
    assert pick.decision_context_snapshot_id == "dcs_test"
    assert pick.scores["adaptive"] == 0.61
    assert pick.scores["calibrated_probability"] == 0.59
    assert pick.meta["recommendation_strength"] == "normal"
    assert pick.meta["adaptive_action"] == "ENTRY"
    assert pick.meta["missing_features"] == ["signal.features.support"]
    assert "candidate" not in pick.scores
    assert "champion" not in pick.scores


def test_historical_replay_observe_is_not_counted_as_recommendation(monkeypatch):
    def fake_outcome(symbol: str, *, as_of: str, horizon: int = 5, **kwargs):
        return {
            "complete": True,
            "symbol": symbol,
            "return_1d": -0.005,
            "return_3d": -0.02,
            "return_5d": -0.03,
            "max_drawdown": -0.04,
            "success": False,
        }

    monkeypatch.setattr(historical_replay, "future_outcome", fake_outcome)
    payload = {
        "decision": "observe",
        "tradeable": False,
        "candidate_pool": [
            {
                "symbol": "000001",
                "probability": {
                    "up_probability_3d": 0.52,
                    "uncertainty": 0.05,
                    "evidence": {"effective_sample_size": 60},
                },
            }
        ],
    }

    evaluated = historical_replay._evaluate_payload(payload, as_of="2026-01-05", pipeline="new", topn=1)
    summary = historical_replay._summary([{"new": evaluated}], pipeline="new")

    assert evaluated["evaluated_picks"] == []
    assert evaluated["evaluated_alternatives"][0]["pick"]["symbol"] == "000001"
    assert evaluated["no_trade_outcome"]["avoided_loss"] is True
    assert summary["days_with_outcomes"] == 0
    assert summary["coverage"] == 0.0
    assert summary["no_trade_days"] == 1
