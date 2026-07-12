from __future__ import annotations

import math

import pandas as pd

from gp_assistant.decision_engine import pipeline
from gp_assistant.decision_engine.adaptive_policy import (
    build_missing_aware_features,
    initial_policy_state,
    score_candidate,
    select_candidates,
    update_policy_state_from_outcomes,
)
from gp_assistant.market_memory.store import make_market_event
from gp_assistant.signal_engine.daily import SignalBuildResult


def _candidate(symbol: str = "000001", **overrides):
    base = {
        "symbol": symbol,
        "code": symbol,
        "signal_type": "breakout_pullback",
        "signal": {
            "signal_type": "breakout_pullback",
            "features": {
                "close": 10.0,
                "atr_pct": 0.03,
                "support": 9.7,
                "pullback_quality": 0.7,
                "volume_ratio": 1.5,
                "liquidity_score": 0.65,
            },
            "feature_vector": {"trend_strength": 0.7, "volume_confirmation": 0.6},
        },
        "probability": {
            "up_probability_3d": 0.58,
            "expected_return_3d": 0.025,
            "drawdown_probability": 0.24,
            "expected_max_drawdown": 0.035,
            "uncertainty": 0.18,
            "confidence": 0.45,
            "evidence": {
                "sample_size": 40,
                "effective_sample_size": 18,
                "mean_similarity": 0.68,
                "success_distribution": {"small_gain": 8},
                "failure_distribution": {"negative_3d": 4},
                "major_failure_modes": [],
            },
        },
        "risk": {
            "execution_quality": 0.62,
            "risk_adjustment": 0.72,
            "drawdown_probability": 0.24,
            "expected_max_drawdown": 0.035,
            "risk_flags": [],
            "diagnostics": {"reward_risk": 1.8, "execution_state": "actionable"},
            "entry": {"price": 10.0},
            "stop": {"price": 9.6},
            "take_profit": {"targets": [10.8]},
        },
        "ranking": {
            "ranking_score": 0.006,
            "ranking_factors": {
                "expected_return_3d": 0.025,
                "win_probability_3d": 0.58,
                "execution_quality": 0.62,
                "confidence": 0.45,
                "risk_adjustment": 0.72,
            },
        },
    }
    base.update(overrides)
    return base


def test_low_sample_still_recommends(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "events"))
    candidate = _candidate(
        probability={
            **_candidate()["probability"],
            "uncertainty": 0.35,
            "evidence": {
                **_candidate()["probability"]["evidence"],
                "sample_size": 5,
                "effective_sample_size": 3,
                "mean_similarity": 0.4,
            },
        }
    )

    result = select_candidates([candidate], topk=1, market_context={"grade": "B"})

    assert result["final_decision"] == "recommend"
    assert result["selected_symbols"]
    assert result["adaptive_candidates"][0]["recommendation_strength"] in {"cautious", "exploratory"}


def test_missing_data_still_recommends(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "events"))
    candidate = _candidate()
    candidate["ranking"] = {"ranking_score": 0.004}
    candidate["signal"] = {"signal_type": "structure_watch", "features": {"close": 10.0}, "feature_vector": {}}
    candidate.pop("historical_cases", None)

    features = build_missing_aware_features(candidate, {"grade": "C"})
    result = select_candidates([candidate], topk=1, market_context={"grade": "C"})

    assert features["feature_coverage"] < 1.0
    assert features["missing_features"]
    assert result["final_decision"] == "recommend"
    assert result["selected_symbols"] == ["000001"]


def test_missing_optional_probability_fields_only_reduce_strength(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "events"))
    candidate = _candidate(probability={"evidence": {}})

    result = select_candidates([candidate], topk=1, market_context={"grade": "C"})

    assert result["final_decision"] == "recommend"
    assert result["selected_symbols"] == ["000001"]
    assert result["adaptive_candidates"][0]["recommendation_strength"] in {"cautious", "exploratory"}


def test_risk_flags_penalize_without_gating(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "events"))
    low_risk = _candidate("000001")
    high_risk = _candidate(
        "000002",
        probability={**_candidate()["probability"], "up_probability_3d": 0.72, "expected_return_3d": 0.06},
        risk={**_candidate()["risk"], "drawdown_probability": 0.70, "risk_flags": ["drawdown_probability_high", "probability_uncertainty_high"]},
        ranking={"ranking_score": 0.02, "ranking_factors": _candidate()["ranking"]["ranking_factors"]},
    )

    low_score = score_candidate(low_risk, {"grade": "B"})
    high_score = score_candidate(high_risk, {"grade": "B"})
    result = select_candidates([low_risk, high_risk], topk=2, market_context={"grade": "B"})

    assert high_score["expert_scores"]["risk"] > low_score["expert_scores"]["risk"]
    assert "000002" in result["selected_symbols"]
    assert result["final_decision"] == "recommend"


def test_structural_invalid_candidates_are_no_trade(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "events"))
    result = select_candidates([{"probability": {}, "risk": {}, "ranking": {}}], topk=1, market_context={"grade": "B"})

    assert result["final_decision"] == "no_trade"
    assert result["selected_symbols"] == []
    assert result["policy_debug"]["invalid_count"] == 1


def test_policy_update_changes_calibration_and_keeps_weights_normalized():
    state = initial_policy_state()
    records = [
        {"rank": 1, "role": "recommended", "pick": _candidate("000001"), "outcome": {"complete": True, "return_3d": 0.04, "max_profit": 0.06, "max_drawdown": -0.01, "success": True}},
        {"rank": 1, "role": "recommended", "pick": _candidate("000002"), "outcome": {"complete": True, "return_3d": -0.04, "max_profit": 0.01, "max_drawdown": -0.06, "success": False}},
    ]

    updated = update_policy_state_from_outcomes(state, records)

    assert updated["update_count"] == 2
    assert sum(bucket["count"] for bucket in updated["calibration"].values()) == 2
    assert math.isclose(sum(updated["expert_weights"].values()), 1.0, abs_tol=1e-6)
    assert all(0.03 <= value <= 0.45 for value in updated["expert_weights"].values())


def test_pipeline_ranked_nonempty_yields_picks_and_adaptive_snapshot(monkeypatch):
    snapshots = []

    class Hub:
        def daily_ohlcv(self, *args, **kwargs):
            dates = pd.bdate_range(end="2026-01-05", periods=120)
            return pd.DataFrame({"date": dates, "close": [10.0] * len(dates)}), {
                "len": 120,
                "freshness_state": "current",
                "strict_blocked": False,
            }

    def fake_signal(symbol, df, as_of, name=None, industry=None, market_context=None, max_history=90):
        event = make_market_event(
            as_of=as_of,
            symbol=symbol,
            signal_type="breakout_pullback",
            feature_vector={"trend_strength": 0.7},
            features={"close": 10.0, "pullback_quality": 0.7, "volume_ratio": 1.4, "liquidity_score": 0.6, "atr_pct": 0.03, "support": 9.7},
            market_context=market_context or {"grade": "B"},
            outcome={"complete": False},
            data_provenance={"source": "test"},
        )
        return SignalBuildResult(event, [], 10.0, as_of, {"ok": True, "rows": 120, "as_of": as_of})

    def fake_probability(current_event, retrieval):
        return {
            "up_probability_3d": 0.61,
            "expected_return_3d": 0.03,
            "drawdown_probability": 0.2,
            "expected_max_drawdown": 0.03,
            "uncertainty": 0.18,
            "confidence": 0.5,
            "evidence": {"sample_size": 20, "effective_sample_size": 12, "mean_similarity": 0.7, "nearest_cases": []},
        }

    def fake_save(snapshot):
        snapshots.append(snapshot)
        return "dcs_adaptive_test"

    monkeypatch.setattr(pipeline, "MarketDataHub", Hub)
    monkeypatch.setattr(pipeline, "build_signal_events_for_symbol", fake_signal)
    monkeypatch.setattr(pipeline, "retrieve_similar_events", lambda *_, **__: {"cases": [], "mean_similarity": 0.7})
    monkeypatch.setattr(pipeline, "infer_probability", fake_probability)
    monkeypatch.setattr(pipeline, "upsert_market_events", lambda events: 0)
    monkeypatch.setattr(pipeline, "save_decision_snapshot", fake_save)

    result = pipeline.run_market_memory_selection(date="2026-01-05", topk=1, symbols=["000001"], prefer_cache_only=True)

    assert result["decision"] == "recommend"
    assert result["tradeable"] is True
    assert result["picks"]
    assert result["picks"][0]["adaptive_policy"]["adaptive_score"] >= 0.0
    assert snapshots
    assert "adaptive_policy_input" in snapshots[0]
    assert "adaptive_policy_output" in snapshots[0]
    assert snapshots[0]["llm_decision_json"]["source"] == "not_used_for_selection"

    monkeypatch.setattr(
        pipeline,
        "load_serenity_policy_state",
        lambda: (_ for _ in ()).throw(AssertionError("historical/off path read production Serenity state")),
    )
    monkeypatch.setattr(
        pipeline,
        "load_frozen_signals",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("historical/off path read live Serenity evidence")),
    )
    monkeypatch.setattr(
        pipeline,
        "save_reference_and_enqueue_pending",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("historical/off path wrote Serenity state")),
    )
    replay_safe = pipeline.run_market_memory_selection(
        date="2026-01-05",
        topk=1,
        symbols=["000001"],
        prefer_cache_only=True,
        serenity_mode="off",
        serenity_persist=False,
    )
    assert replay_safe["decision"] == "recommend"
    assert replay_safe["adaptive_policy"]["serenity_policy"]["applied_weight"] == 0.0
