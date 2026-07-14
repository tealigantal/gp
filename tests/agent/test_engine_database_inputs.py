from __future__ import annotations

from gp_assistant.book.daybook import _map_pick
from gp_assistant.market_memory.retrieval import retrieve_similar_events
from gp_assistant.market_memory.store import make_market_event, upsert_market_event


def _event(symbol: str, *, as_of: str, complete: bool, value: float, outcome_available: str | None = None):
    vector = {name: value for name in (
        "trend_strength", "pullback_quality", "volume_confirmation", "atr_pct", "extension_pct",
        "support_distance_pct", "liquidity_score", "market_regime_score", "industry_strength_score", "price_position_score",
    )}
    return make_market_event(
        as_of=as_of, symbol=symbol, signal_type="breakout_pullback", feature_vector=vector,
        features={"close": 10.0, "volume_ratio": 1.2, "atr_pct": 0.03},
        market_context={"market_regime": "B"},
        outcome={"complete": complete, "return_3d": 0.04, "max_drawdown": -0.01, "stop_hit": False, "outcome_available_trading_day": outcome_available},
        data_provenance={"source": "isolated-test", "daily_as_of": as_of},
    )


def test_core_engine_reads_only_pre_asof_completed_market_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))
    current = _event("600000", as_of="2026-07-13", complete=False, value=0.10)
    past = _event("600001", as_of="2026-07-03", complete=True, value=0.11, outcome_available="2026-07-10")
    future = _event("600002", as_of="2026-07-14", complete=True, value=0.10, outcome_available="2026-07-21")
    incomplete = _event("600003", as_of="2026-07-09", complete=False, value=0.10)
    for event in (past, future, incomplete):
        upsert_market_event(event)
    retrieval = retrieve_similar_events(current, as_of="2026-07-13", k=10)
    assert retrieval["retrieval_method"] == "normalized_feature_vector_distance"
    assert [case["symbol"] for case in retrieval["cases"]] == ["600001"]
    assert retrieval["cases"][0]["features"]["close"] == 10.0
    assert retrieval["cases"][0]["market_context"]["market_regime"] == "B"
    assert retrieval["cases"][0]["outcome"]["return_3d"] == 0.04


def test_daybook_projection_keeps_professional_recommendation_fields():
    item = {
        "symbol": "600000", "name": "浦发银行", "signal_type": "breakout_pullback",
        "probability": {"up_probability_3d": 0.62, "expected_return_3d": 0.02, "confidence": 0.71, "uncertainty": 0.11, "evidence": {"sample_size": 80, "effective_sample_size": 63, "mean_similarity": 0.84}},
        "risk": {"execution_quality": 0.7, "risk_flags": ["gap_risk"]}, "ranking": {"ranking_score": 0.08},
        "adaptive_policy": {"adaptive_score": 0.61, "decision_score": 0.61, "calibrated_probability": 0.60, "recommendation_strength": "normal", "action": "ENTRY", "feature_coverage": 0.9},
        "trade_plan": {"entry": {"low": 10.0, "high": 10.2}, "stop": {"price": 9.6}, "take_profit": {"targets": [10.8]}, "diagnostics": {"reward_risk": 2.0, "actionable": True}},
        "why_selected_text": "趋势、量能和相似案例均支持该计划。", "historical_cases": [{"event_id": "mme_1", "similarity": 0.9}],
    }
    pick = _map_pick(1, item)
    assert pick.entry_plan["low"] == 10.0
    assert pick.stop_plan["price"] == 9.6
    assert pick.take_profit_plan["targets"] == [10.8]
    assert pick.probability["evidence"]["effective_sample_size"] == 63
    assert pick.risk_flags == ["gap_risk"]
    assert pick.why_selected
