from __future__ import annotations

import pytest

from gp_assistant.decision_engine.adaptive_policy import select_candidates
from gp_assistant.serenity.models import FrozenSerenitySignal, SerenityPolicyState
from tests.decision_engine.test_adaptive_policy import _candidate


def _state(stage: str = "active", weight: float = 0.08) -> SerenityPolicyState:
    return SerenityPolicyState(
        state=stage,
        applied_weight=weight,
        max_weight=0.08,
        bootstrap_run_id="serboot-native",
        state_since="2026-07-14T00:00:00+08:00",
        updated_at="2026-07-14T00:00:00+08:00",
    )


def _signal(symbol: str, alpha: float, *, status: str = "available") -> FrozenSerenitySignal:
    available = status == "available"
    return FrozenSerenitySignal(
        symbol=symbol,
        status=status,
        availability=1 if available else 0,
        learning_eligible=available,
        direction=1 if alpha > 0 else -1 if alpha < 0 else 0,
        alpha_value=alpha if available else 0.0,
        confidence=abs(alpha) if available else 0.0,
        source_quality=1.0 if available else 0.0,
        decision_at="2026-07-14T10:00:00+08:00",
        generated_at="2026-07-14T10:00:00+08:00",
        target_id="sertarget-native",
        source_run_id="serrun-native",
        input_hash=f"hash-{symbol}-{status}-{alpha}",
    )


def test_native_alpha_is_the_ninth_expert_in_the_single_final_score():
    candidates = [_candidate("000001"), _candidate("000002")]
    result = select_candidates(
        candidates,
        topk=2,
        market_context={"grade": "B"},
        serenity_signals={
            "000001": _signal("000001", -1.0),
            "000002": _signal("000002", 1.0),
        },
        serenity_policy_state=_state(),
        serenity_mode="native",
        require_serenity=True,
    )

    assert result["final_decision"] == "recommend"
    assert result["selected_symbols"][0] == "000002"
    for row in result["adaptive_candidates"]:
        assert len(row["expert_scores"]) == 9
        assert "serenity" in row["expert_scores"]
        assert row["decision_score"] == pytest.approx(
            row["baseline_adaptive_score"] + row["serenity_adjustment"]
        )


def test_complete_empty_official_poll_is_a_neutral_native_expert():
    signal = _signal("000001", 0.0, status="no_relevant_evidence")
    result = select_candidates(
        [_candidate("000001")],
        topk=1,
        market_context={"grade": "B"},
        serenity_signals={"000001": signal},
        serenity_policy_state=_state("shadow", 0.0),
        serenity_mode="native",
        require_serenity=True,
    )

    assert result["final_decision"] == "recommend"
    row = result["adaptive_candidates"][0]
    assert row["expert_scores"]["serenity"] == 0.0
    assert row["serenity_adjustment"] == 0.0


def test_incomplete_target_zeroes_serenity_and_preserves_base_recommendation():
    result = select_candidates(
        [_candidate("000001")],
        topk=1,
        market_context={"grade": "B"},
        serenity_signals={"000001": _signal("000001", 0.0, status="not_ready")},
        serenity_policy_state=_state("shadow", 0.0),
        serenity_mode="native",
        require_serenity=True,
    )

    assert result["final_decision"] == "recommend"
    assert result["selected_symbols"] == ["000001"]
    assert result["serenity_policy"]["applied_weight"] == 0.0
    assert result["serenity_policy"]["degraded_to_zero"] is True
    assert result["adaptive_candidates"][0]["serenity_adjustment"] == 0.0
