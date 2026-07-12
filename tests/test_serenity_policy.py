import pytest
from pydantic import ValidationError

from gp_assistant.decision_engine.serenity_policy import (
    apply_serenity_addon,
    build_reference_snapshot,
    build_serenity_counterfactuals,
    decision_score,
)
from gp_assistant.serenity.models import FrozenSerenitySignal, SerenityPolicyState


def _signal(
    symbol: str,
    direction: int,
    status: str = "available",
    *,
    learning_eligible: bool = True,
) -> FrozenSerenitySignal:
    return FrozenSerenitySignal(
        symbol=symbol,
        status=status,
        availability=1 if status == "available" else 0,
        learning_eligible=status == "available" and learning_eligible,
        direction=direction,
        confidence=1.0,
        source_quality=1.0,
        decision_at="2026-07-10T15:00:00+08:00",
        generated_at="2026-07-10T15:00:00+08:00",
        input_hash=f"hash-{symbol}",
    )


def _state(state: str, weight: float) -> SerenityPolicyState:
    return SerenityPolicyState(
        state=state,
        applied_weight=weight,
        max_weight=0.08,
        bootstrap_run_id="serboot_test",
        state_since="2026-07-01T00:00:00+08:00",
        updated_at="2026-07-01T00:00:00+08:00",
    )


def test_shadow_is_bit_for_bit_selection_invariant():
    base = {
        "final_decision": "recommend",
        "selected_symbols": ["000001", "000002"],
        "adaptive_candidates": [
            {"symbol": "000001", "adaptive_score": 0.60, "action": "ENTRY"},
            {"symbol": "000002", "adaptive_score": 0.59, "action": "ENTRY"},
        ],
        "validator_result": {"ok": True},
    }
    out = apply_serenity_addon(base, {"000002": _signal("000002", 1)}, _state("shadow", 0), topk=2, mode="auto")
    assert out["selected_symbols"] == base["selected_symbols"]
    assert [row["adaptive_score"] for row in out["adaptive_candidates"]] == [0.60, 0.59]
    assert all(row["serenity_adjustment"] == 0 for row in out["adaptive_candidates"])


def test_active_weight_can_change_close_ranking_but_missing_never_penalizes():
    base = {
        "final_decision": "recommend",
        "selected_symbols": ["000001"],
        "adaptive_candidates": [
            {"symbol": "000001", "adaptive_score": 0.60},
            {"symbol": "000002", "adaptive_score": 0.57},
        ],
    }
    out = apply_serenity_addon(base, {"000002": _signal("000002", 1)}, _state("active", 0.08), topk=1, mode="auto")
    assert out["selected_symbols"] == ["000002"]
    score, adjustment = decision_score(0.60, _signal("000001", -1, status="stale"), 0.08)
    assert score == 0.60
    assert adjustment == 0.0
    arms = build_serenity_counterfactuals(base["adaptive_candidates"], {"000002": _signal("000002", 1)}, topk=1)
    assert [arm.weight for arm in arms] == [step / 100 for step in range(9)]


def test_backfill_only_signal_can_show_reference_counterfactual_but_never_bind():
    base = {
        "final_decision": "recommend",
        "selected_symbols": ["000001"],
        "adaptive_candidates": [
            {"symbol": "000001", "adaptive_score": 0.60},
            {"symbol": "000002", "adaptive_score": 0.57},
        ],
    }
    signal = _signal("000002", 1, learning_eligible=False)
    out = apply_serenity_addon(base, {"000002": signal}, _state("active", 0.08), topk=1, mode="auto")
    assert out["selected_symbols"] == ["000001"]
    assert next(
        row for row in out["adaptive_candidates"] if row["symbol"] == "000002"
    )["serenity_non_binding"] is True
    assert out["serenity_policy"]["reference_would_change_topk"] is True
    assert out["serenity_reference_counterfactuals"][-1]["selected_symbols"] == ["000002"]


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), 0.09, -0.01])
def test_invalid_policy_weight_is_rejected_instead_of_silently_clamped(weight):
    with pytest.raises(ValidationError, match="non_finite_or_out_of_bounds"):
        _state("active", weight)


def test_learning_sample_uses_explicit_trading_day_not_generation_clock():
    signal = _signal("000001", 1)
    adaptive = apply_serenity_addon(
        {
            "final_decision": "recommend",
            "selected_symbols": ["000001"],
            "adaptive_candidates": [{"symbol": "000001", "adaptive_score": 0.60}],
        },
        {"000001": signal},
        _state("shadow", 0),
        topk=1,
        mode="auto",
    )
    kwargs = {
        "decision_context_snapshot_id": "dcs_day_key",
        "adaptive_output": adaptive,
        "signals": {"000001": signal},
        "risk_plans": {
            "000001": {
                "entry": {"price": 10},
                "stop": {"price": 9},
                "take_profit": {"price": 12},
            }
        },
    }
    first = build_reference_snapshot(
        **kwargs,
        decision_day="2026-07-10",
        decision_at="2026-07-10T23:59:00+08:00",
    )
    rebuilt = build_reference_snapshot(
        **kwargs,
        decision_day="2026-07-10",
        decision_at="2026-07-11T01:00:00+08:00",
    )
    next_day = build_reference_snapshot(
        **kwargs,
        decision_day="2026-07-11",
        decision_at="2026-07-11T01:00:00+08:00",
    )

    assert rebuilt.learning_sample_id == first.learning_sample_id
    assert next_day.learning_sample_id != first.learning_sample_id
    assert rebuilt.snapshot_id != first.snapshot_id
