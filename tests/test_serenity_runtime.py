from datetime import date, datetime, timezone

import pytest

from gp_assistant.decision_engine.serenity_policy import build_reference_snapshot, counterfactual_arm_checksum
from gp_assistant.serenity.evaluation import (
    evaluate_pending_item,
    process_pending_evaluations,
    recover_legacy_reference_snapshot_validation_suspension_after_complete_poll,
    update_policy_from_evaluations,
)
from gp_assistant.serenity.models import FrozenSerenitySignal, NATIVE_SERENITY_FORMULA_VERSION, SerenityPolicyState
from gp_assistant.serenity.sources import SourceError
from gp_assistant.serenity.store import (
    load_cursor,
    load_policy_state,
    load_source_progress,
    lookup_document,
    status_snapshot,
)
from gp_assistant.serenity.worker import (
    _consecutive_counts,
    _next_consecutive_counts,
    run_serenity_once,
)


def _state(stage="shadow", weight=0.0):
    return SerenityPolicyState(
        state=stage,
        applied_weight=weight,
        max_weight=0.08,
        bootstrap_run_id="serboot_test",
        state_since="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def test_source_failure_streak_requires_complete_success_status():
    assert _consecutive_counts(
        [{"complete": False, "status": "partial"} for _ in range(3)]
    )[1] == 3
    assert _consecutive_counts(
        [{"complete": True, "status": "partial"} for _ in range(3)]
    )[1] == 3


def test_current_poll_result_resets_or_extends_the_correct_schedule_streak():
    failure_history = [
        {"complete": False, "status": "failed", "item_count": 0}
        for _ in range(5)
    ]
    empty_history = [
        {"complete": True, "status": "success", "item_count": 0}
        for _ in range(4)
    ]

    assert _next_consecutive_counts(
        failure_history, source_complete=True, item_count=2
    ) == (0, 0)
    assert _next_consecutive_counts(
        empty_history, source_complete=True, item_count=0
    ) == (5, 0)
    assert _next_consecutive_counts(
        empty_history, source_complete=False, item_count=0
    ) == (0, 1)


def _reference():
    signal = FrozenSerenitySignal(
        symbol="000001",
        status="available",
        availability=1,
        learning_eligible=True,
        direction=1,
        confidence=1.0,
        source_quality=1.0,
        decision_at="2026-01-02T15:00:00+08:00",
        generated_at="2026-01-02T15:00:00+08:00",
        input_hash="signal-hash",
    )
    arms = [
        {
            "weight": step / 100,
            "ranked_symbols": ["000001"],
            "selected_symbols": ["000001"],
            "scores": {"000001": 0.6 + step / 100},
        }
        for step in range(9)
    ]
    for arm in arms:
        arm["checksum"] = counterfactual_arm_checksum(arm)
    adaptive = {
        "adaptive_candidates": [{"symbol": "000001", "adaptive_score": 0.6}],
        "selected_symbols": ["000001"],
        "serenity_policy": {
            "state": "shadow",
            "applied_weight": 0.0,
            "max_weight": 0.08,
            "baseline_selected_symbols": ["000001"],
            "applied_selected_symbols": ["000001"],
        },
        "serenity_counterfactuals": arms,
    }
    return build_reference_snapshot(
        decision_context_snapshot_id="dcs_1",
        decision_day="2026-01-02",
        decision_at="2026-01-02T15:00:00+08:00",
        adaptive_output=adaptive,
        signals={"000001": signal},
        risk_plans={
            "000001": {
                "entry": {"price": 10},
                "stop": {"price": 9},
                "take_profit": {"price": 12},
            }
        },
    )


def test_evaluation_waits_until_day_after_t5(monkeypatch):
    reference = _reference()
    monkeypatch.setattr("gp_assistant.serenity.evaluation.load_reference_snapshot", lambda _: reference)
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.load_decision_snapshot",
        lambda _: {
            "snapshot_id": "dcs_1",
            "as_of": "2026-01-02",
            "decision_trade_day": "2026-01-02",
            "risk_output": {"000001": {"entry": {"price": 10}, "stop": {"price": 9}, "take_profit": {"price": 12}}},
        },
    )
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.future_outcome",
        lambda *args, **kwargs: {
            "complete": True,
            "symbol": "000001",
            "matured_at": "2026-01-09",
            "filled": True,
            "net_return_3d": 0.02,
            "net_return_5d": 0.03,
            "max_drawdown": -0.01,
            "t5_finalized": True,
        },
    )
    pending = {
        "reference_snapshot_id": reference.snapshot_id,
        "decision_context_snapshot_id": "dcs_1",
        "decision_day": "2026-01-02",
        "epoch": 1,
        "learning_eligible": True,
        "formula_version": NATIVE_SERENITY_FORMULA_VERSION,
        "input_hash": reference.input_checksum,
    }
    monkeypatch.setattr("gp_assistant.serenity.evaluation.next_trading_day_on_or_after", lambda _: "20260112")
    assert evaluate_pending_item(pending, today=date(2026, 1, 9)) is None
    assert evaluate_pending_item(pending, today=date(2026, 1, 10)) is None
    assert evaluate_pending_item(pending, today=date(2026, 1, 12))["matured_at"] == "2026-01-09"


def test_previous_completed_as_of_uses_explicit_decision_trade_day(monkeypatch):
    reference = _reference()
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.load_reference_snapshot",
        lambda _: reference,
    )
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.load_decision_snapshot",
        lambda _: {
            "snapshot_id": "dcs_1",
            "as_of": "2026-01-01",
            "decision_trade_day": "2026-01-02",
            "risk_output": reference.risk_plans,
        },
    )
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.future_outcome",
        lambda *args, **kwargs: {"complete": False},
    )
    pending = {
        "reference_snapshot_id": reference.snapshot_id,
        "decision_context_snapshot_id": "dcs_1",
        "decision_day": "2026-01-02",
        "epoch": 1,
        "formula_version": NATIVE_SERENITY_FORMULA_VERSION,
        "input_hash": reference.input_checksum,
    }

    assert evaluate_pending_item(pending, today=date(2026, 1, 12)) is None


def test_reference_tampering_is_detected_before_outcome_learning(monkeypatch):
    reference = _reference()
    arms = list(reference.counterfactual_arms)
    arms[1] = arms[1].model_copy(update={"scores": {"000001": 0.99}})
    tampered = reference.model_copy(update={"counterfactual_arms": arms})
    monkeypatch.setattr("gp_assistant.serenity.evaluation.load_reference_snapshot", lambda _: tampered)
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.load_decision_snapshot",
        lambda _: {
            "snapshot_id": "dcs_1",
            "as_of": "2026-01-02",
            "decision_trade_day": "2026-01-02",
            "risk_output": {},
        },
    )
    payload = evaluate_pending_item(
        {
            "reference_snapshot_id": reference.snapshot_id,
            "decision_context_snapshot_id": "dcs_1",
            "decision_day": "2026-01-02",
            "epoch": 1,
            "formula_version": NATIVE_SERENITY_FORMULA_VERSION,
            "input_hash": reference.input_checksum,
        }
    )
    assert "reference_content_checksum_mismatch" in payload["integrity_errors"]
    assert any(item.startswith("counterfactual_arm_checksum_mismatch:") for item in payload["integrity_errors"])


def test_mutated_decision_risk_plan_is_detected_before_outcome_learning(monkeypatch):
    reference = _reference()
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.load_reference_snapshot", lambda _: reference
    )
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.load_decision_snapshot",
        lambda _: {
            "snapshot_id": "dcs_1",
            "as_of": "2026-01-02",
            "decision_trade_day": "2026-01-02",
            "risk_output": {
                "000001": {
                    "entry": {"price": 99},
                    "stop": {"price": 9},
                    "take_profit": {"price": 12},
                }
            },
        },
    )
    payload = evaluate_pending_item(
        {
            "reference_snapshot_id": reference.snapshot_id,
            "decision_context_snapshot_id": "dcs_1",
            "decision_day": "2026-01-02",
            "epoch": 1,
            "formula_version": NATIVE_SERENITY_FORMULA_VERSION,
            "input_hash": reference.input_checksum,
        }
    )
    assert "decision_risk_plan_mismatch:000001" in payload["integrity_errors"]


def test_missing_reference_becomes_terminal_integrity_result(monkeypatch):
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.load_reference_snapshot", lambda _: None
    )
    payload = evaluate_pending_item(
        {
            "reference_snapshot_id": "missing",
            "decision_context_snapshot_id": "dcs_missing",
            "decision_day": "2026-01-02",
            "epoch": 1,
            "formula_version": NATIVE_SERENITY_FORMULA_VERSION,
            "input_hash": "hash",
        }
    )
    assert payload["learning_eligible"] is False
    assert payload["integrity_errors"] == ["reference_snapshot_missing"]


def test_unfinalized_t5_never_matures(monkeypatch):
    reference = _reference()
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.load_reference_snapshot", lambda _: reference
    )
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.load_decision_snapshot",
        lambda _: {
            "snapshot_id": "dcs_1",
            "as_of": "2026-01-02",
            "decision_trade_day": "2026-01-02",
            "risk_output": reference.risk_plans,
        },
    )
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.future_outcome",
        lambda *args, **kwargs: {
            "complete": True,
            "symbol": "000001",
            "matured_at": "2026-01-09",
            "t5_finalized": False,
        },
    )
    pending = {
        "reference_snapshot_id": reference.snapshot_id,
        "decision_context_snapshot_id": "dcs_1",
        "decision_day": "2026-01-02",
        "epoch": 1,
        "formula_version": NATIVE_SERENITY_FORMULA_VERSION,
        "input_hash": reference.input_checksum,
    }
    assert evaluate_pending_item(pending, today=date(2026, 1, 12)) is None


def test_incomplete_outcome_for_any_arm_union_symbol_skips_whole_day(monkeypatch):
    first = _reference().signals["000001"]
    second = first.model_copy(
        update={"symbol": "000002", "input_hash": "signal-hash-2"}
    )
    arms = []
    for step in range(9):
        selected = "000002" if step == 8 else "000001"
        other = "000001" if selected == "000002" else "000002"
        arm = {
            "weight": step / 100,
            "ranked_symbols": [selected, other],
            "selected_symbols": [selected],
            "scores": {"000001": 0.6, "000002": 0.59 + step / 100},
        }
        arm["checksum"] = counterfactual_arm_checksum(arm)
        arms.append(arm)
    reference = build_reference_snapshot(
        decision_context_snapshot_id="dcs_union",
        decision_day="2026-01-02",
        decision_at="2026-01-02T15:00:00+08:00",
        adaptive_output={
            "serenity_policy": {
                "state": "shadow",
                "applied_weight": 0.0,
                "baseline_selected_symbols": ["000001"],
                "applied_selected_symbols": ["000001"],
            },
            "serenity_counterfactuals": arms,
        },
        signals={"000001": first, "000002": second},
        risk_plans={
            symbol: {
                "entry": {"price": 10},
                "stop": {"price": 9},
                "take_profit": {"price": 12},
            }
            for symbol in ("000001", "000002")
        },
    )
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.load_reference_snapshot", lambda _: reference
    )
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.load_decision_snapshot",
        lambda _: {
            "snapshot_id": "dcs_union",
            "as_of": "2026-01-02",
            "decision_trade_day": "2026-01-02",
            "risk_output": reference.risk_plans,
        },
    )
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.future_outcome",
        lambda symbol, **kwargs: {
            "complete": symbol == "000001",
            "t5_finalized": symbol == "000001",
            "symbol": symbol,
            "matured_at": "2026-01-09",
        },
    )
    assert (
        evaluate_pending_item(
            {
                "reference_snapshot_id": reference.snapshot_id,
                "decision_context_snapshot_id": "dcs_union",
                "decision_day": "2026-01-02",
                "epoch": 1,
                    "formula_version": NATIVE_SERENITY_FORMULA_VERSION,
                "input_hash": reference.input_checksum,
            },
            today=date(2026, 1, 12),
        )
        is None
    )


def _evaluation(idx: int, delta: float = 0.002):
    arms = {
        f"{step / 100:.2f}": {
            "delta": 0.0 if step == 0 else delta,
            "max_drawdown": -0.02,
            "turnover_delta": 0.05 if step else 0.0,
        }
        for step in range(9)
    }
    return {
        "evaluation_id": f"eval-{idx}",
        "decision_day": f"2026-{1 + idx // 28:02d}-{1 + idx % 28:02d}",
        "matured_at": f"2026-{1 + idx // 28:02d}-{6 + idx % 22:02d}",
        "epoch": 1,
        "learning_eligible": True,
        "available_results": 4,
        "supportive_count": 2,
        "conflicting_count": 2,
        "integrity_errors": [],
        "arms": arms,
        "created_at": f"2026-06-{1 + idx % 28:02d}T00:00:00+00:00",
    }


def test_shadow_can_only_promote_after_full_forward_gate(monkeypatch):
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.recent_poll_outcomes",
        lambda *args, **kwargs: [{"complete": 1, "status": "success"} for _ in range(20)],
    )
    promoted = update_policy_from_evaluations(_state(), [_evaluation(idx) for idx in range(100)])
    assert promoted.state == "probation"
    assert promoted.applied_weight == 0.01


def test_integrity_error_suspends_and_zeros_weight(monkeypatch):
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.recent_poll_outcomes",
        lambda *args, **kwargs: [{"complete": 1, "status": "success"} for _ in range(20)],
    )
    row = _evaluation(1)
    row["integrity_errors"] = ["reference_input_hash_mismatch"]
    suspended = update_policy_from_evaluations(_state("active", 0.05), [row])
    assert suspended.state == "suspended"
    assert suspended.applied_weight == 0.0
    assert "reference_input_hash_mismatch" in suspended.suspension_reasons


def test_currently_valid_legacy_reference_schema_error_does_not_resuspend(monkeypatch):
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.recent_poll_outcomes",
        lambda *args, **kwargs: [{"complete": 1, "status": "success"} for _ in range(20)],
    )
    reference = _reference()
    row = _evaluation(1)
    row.update(
        {
            "integrity_errors": ["reference_snapshot_unreadable:ValidationError"],
            "reference_snapshot_id": reference.snapshot_id,
            "input_hash": reference.input_checksum,
        }
    )
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.load_reference_snapshot",
        lambda _: reference,
    )

    updated = update_policy_from_evaluations(_state("active", 0.05), [row])

    assert updated.state == "active"
    assert updated.applied_weight == 0.04


def test_complete_poll_recovers_only_the_proven_legacy_schema_false_positive(monkeypatch):
    reference = _reference()
    state = _state("suspended", 0.0).model_copy(
        update={
            "suspension_reasons": [
                "reference_snapshot_unreadable:ValidationError",
                "three_consecutive_source_or_parse_failures",
            ],
            "cooldown_until": "2026-02-01T00:00:00+00:00",
        }
    )
    row = _evaluation(1)
    row.update(
        {
            "integrity_errors": ["reference_snapshot_unreadable:ValidationError"],
            "reference_snapshot_id": reference.snapshot_id,
            "input_hash": reference.input_checksum,
        }
    )
    saved = []
    monkeypatch.setattr("gp_assistant.serenity.evaluation.load_policy_state", lambda: state)
    monkeypatch.setattr("gp_assistant.serenity.evaluation.list_evaluations", lambda **_: [row])
    monkeypatch.setattr("gp_assistant.serenity.evaluation.load_reference_snapshot", lambda _: reference)
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.save_policy_state_with_ledger",
        lambda next_state, **kwargs: saved.append((next_state, kwargs)) or next_state,
    )

    recovered = recover_legacy_reference_snapshot_validation_suspension_after_complete_poll()

    assert recovered.state == "shadow"
    assert recovered.applied_weight == 0.0
    assert recovered.suspension_reasons == []
    assert saved[0][1]["ledger_payload"]["transition"] == "legacy_reference_schema_validated_to_shadow"


def test_source_level_incomplete_partial_poll_blocks_readiness_without_mutating_policy(monkeypatch):
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.recent_poll_outcomes",
        lambda *args, **kwargs: [
            {"complete": 0, "status": "partial"} for _ in range(3)
        ],
    )
    state = _state(stage="active", weight=0.02)

    unchanged = update_policy_from_evaluations(
        state,
        [_evaluation(idx) for idx in range(20)],
    )

    assert unchanged.state == "active"
    assert unchanged.applied_weight == 0.01
    assert unchanged.suspension_reasons == []


def test_policy_metrics_block_bootstrap_by_unique_decision_day(monkeypatch):
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.recent_poll_outcomes",
        lambda *args, **kwargs: [{"complete": 1, "status": "success"} for _ in range(20)],
    )
    rows = [_evaluation(idx) for idx in range(40)]
    duplicate = dict(rows[-1])
    duplicate["evaluation_id"] = "duplicate-same-day"
    updated = update_policy_from_evaluations(_state(), [*rows, duplicate])
    assert updated.matured_days == 40
    assert updated.rolling_metrics["arms"]["0.01"]["count"] == 40


def test_repeated_identical_learning_sample_cannot_inflate_promotion_counts(monkeypatch):
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.recent_poll_outcomes",
        lambda *args, **kwargs: [{"complete": 1, "status": "success"} for _ in range(20)],
    )
    rows = [
        {**_evaluation(idx), "learning_sample_id": "same-frozen-decision"}
        for idx in range(100)
    ]
    updated = update_policy_from_evaluations(_state(), rows)
    assert updated.state == "shadow"
    assert updated.decision_snapshots == 1
    assert updated.available_results == 4


def _metric_stub(rows, weight):
    count = len({str(row.get("decision_day") or "") for row in rows})
    positive = weight >= 0.04
    return {
        "weight": weight,
        "count": count,
        "mean_delta": 0.002 if positive else -0.001,
        "lcb95": 0.001 if positive else -0.002,
        "ucb95": 0.003,
        "standard_error": 0.0,
        "mdd_worsening": 0.0,
        "turnover_delta": 0.05,
        "positive_10d_windows": 4 if positive else 0,
        "window_count": 4,
    }


def test_active_weight_moves_one_point_after_two_passes_and_one_failure(monkeypatch):
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.recent_poll_outcomes",
        lambda *args, **kwargs: [{"complete": 1, "status": "success"} for _ in range(20)],
    )
    monkeypatch.setattr("gp_assistant.serenity.evaluation._metrics", _metric_stub)
    rows = [_evaluation(idx) for idx in range(60)]
    state = _state("active", 0.02)
    first = update_policy_from_evaluations(state, rows)
    assert first.applied_weight == 0.02
    assert first.consecutive_passes == 1
    second = update_policy_from_evaluations(first, rows)
    assert second.applied_weight == 0.03
    assert second.consecutive_passes == 0

    def only_low_weight_passes(values, weight):
        result = _metric_stub(values, weight)
        result.update(
            {
                "mean_delta": 0.002 if weight == 0.01 else -0.001,
                "lcb95": 0.001 if weight == 0.01 else -0.002,
            }
        )
        return result

    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation._metrics", only_low_weight_passes
    )
    reduced = update_policy_from_evaluations(second, rows)
    assert reduced.applied_weight == 0.02


def test_probation_requires_four_distinct_five_day_pass_windows(monkeypatch):
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.recent_poll_outcomes",
        lambda *args, **kwargs: [{"complete": 1, "status": "success"} for _ in range(20)],
    )

    def passing_metrics(rows, weight):
        result = _metric_stub(rows, max(weight, 0.04))
        result["weight"] = weight
        return result

    monkeypatch.setattr("gp_assistant.serenity.evaluation._metrics", passing_metrics)
    state = _state("probation", 0.01).model_copy(
        update={"state_since": "2020-01-01T00:00:00+00:00"}
    )
    for pass_index, count in enumerate((40, 45, 50), start=1):
        rows = [
            {**_evaluation(idx), "available_results": 8}
            for idx in range(count)
        ]
        state = update_policy_from_evaluations(state, rows)
        assert state.state == "probation"
        assert state.consecutive_passes == pass_index
    rows = [
        {**_evaluation(idx), "available_results": 8}
        for idx in range(55)
    ]
    state = update_policy_from_evaluations(state, rows)
    assert state.state == "active"
    assert state.applied_weight == 0.02


def test_suspended_policy_recovers_only_after_clean_forward_evidence(monkeypatch):
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.recent_poll_outcomes",
        lambda *args, **kwargs: [{"complete": 1, "status": "success"} for _ in range(20)],
    )
    rows = [
        {**_evaluation(idx), "available_results": 6}
        for idx in range(20)
    ]
    state = _state("suspended", 0.0).model_copy(
        update={
            "cooldown_until": "2020-01-01T00:00:00+00:00",
            "state_since": "2020-01-01T00:00:00+00:00",
            "suspension_reasons": ["test"],
        }
    )
    recovered = update_policy_from_evaluations(state, rows)
    assert recovered.state == "shadow"
    assert recovered.applied_weight == 0.0
    assert recovered.epoch == state.epoch + 1
    assert recovered.suspension_reasons == []


def test_policy_updates_only_after_five_new_unique_mature_days(monkeypatch):
    evaluations = [_evaluation(idx) for idx in range(5)]
    state = _state()
    monkeypatch.setattr("gp_assistant.serenity.evaluation.list_pending_evaluations", lambda limit=200: [{"pending_id": "p"}])
    monkeypatch.setattr("gp_assistant.serenity.evaluation.evaluate_pending_item", lambda *args, **kwargs: evaluations[-1])
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.commit_evaluation_result",
        lambda payload, pending_id: (payload["evaluation_id"], True),
    )
    monkeypatch.setattr("gp_assistant.serenity.evaluation.load_policy_state", lambda: state)
    monkeypatch.setattr("gp_assistant.serenity.evaluation.list_evaluations", lambda **kwargs: evaluations)
    monkeypatch.setattr("gp_assistant.serenity.evaluation.recent_poll_outcomes", lambda *args, **kwargs: [{"complete": 1, "status": "success"}] * 20)
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.save_policy_state_with_ledger",
        lambda value, **kwargs: value,
    )
    assert process_pending_evaluations(today=date(2026, 7, 11))["policy_updated"] is True

    state = _state().model_copy(update={"rolling_metrics": {"last_policy_evaluated_matured_days": 2}})
    monkeypatch.setattr("gp_assistant.serenity.evaluation.load_policy_state", lambda: state)
    assert process_pending_evaluations(today=date(2026, 7, 11))["policy_updated"] is False


def test_non_learning_rows_cannot_replay_same_policy_window(monkeypatch):
    eligible = [_evaluation(idx) for idx in range(5)]
    excluded = [
        {
            **_evaluation(100 + idx),
            "evaluation_id": f"excluded-{idx}",
            "learning_eligible": False,
        }
        for idx in range(20)
    ]
    state = _state().model_copy(
        update={"rolling_metrics": {"last_policy_evaluated_matured_days": 5}}
    )
    monkeypatch.setattr("gp_assistant.serenity.evaluation.list_pending_evaluations", lambda limit=200: [])
    monkeypatch.setattr("gp_assistant.serenity.evaluation.load_policy_state", lambda: state)
    monkeypatch.setattr(
        "gp_assistant.serenity.evaluation.list_evaluations",
        lambda **kwargs: [*eligible, *excluded],
    )
    result = process_pending_evaluations(today=date(2026, 7, 11))
    assert result["policy_updated"] is False
    assert result["applied_weight"] == 0.0


class _EmptyRealClient:
    request_count = 0

    def load_stock_map(self):
        self.request_count += 1
        return {"000001": {"org_id": "gssz0000001"}}

    def fetch_symbol(self, symbol, org_id, *, start, end, start_page=1):
        self.request_count += 1
        return {"records": [], "complete": True, "backlog": False, "schema_fingerprint": "schema"}


def test_fixture_poll_cannot_make_experiment_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    now = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)
    run_serenity_once(
        symbols=["000001"],
        source_kind="test",
        client=_EmptyRealClient(),
        verifier=None,
        now=now,
    )
    assert load_policy_state().state == "warming"
    assert status_snapshot()["available"] is False

    run_serenity_once(
        symbols=["000001"],
        source_kind="test",
        bootstrap=True,
        lookback_days=30,
        client=_EmptyRealClient(),
        verifier=None,
        now=now,
    )
    assert load_policy_state().state == "warming"
    assert status_snapshot()["bootstrap_ready"] is False

    run_serenity_once(
        symbols=["000001"],
        source_kind="live",
        client=_EmptyRealClient(),
        verifier=None,
        now=now,
    )
    assert load_policy_state().state == "warming"
    assert status_snapshot()["bootstrap_ready"] is False

    run_serenity_once(
        symbols=["000001"],
        bootstrap=True,
        lookback_days=30,
        client=_EmptyRealClient(),
        verifier=None,
        now=now,
    )
    assert load_policy_state().state == "warming"
    assert status_snapshot()["bootstrap_ready"] is False


class _BacklogClient(_EmptyRealClient):
    def __init__(self):
        self.request_count = 0
        self.start_pages = []

    def fetch_symbol(self, symbol, org_id, *, start, end, start_page=1):
        self.request_count += 1
        self.start_pages.append(start_page)
        if len(self.start_pages) == 1:
            return {
                "records": [],
                "complete": False,
                "backlog": True,
                "schema_fingerprint": "schema",
                "next_page": 2,
            }
        return {
            "records": [],
            "complete": True,
            "backlog": False,
            "schema_fingerprint": "schema",
            "next_page": None,
        }


def test_backlog_page_checkpoint_resumes_instead_of_restarting(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    client = _BacklogClient()
    now = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)
    first = run_serenity_once(symbols=["000001"], client=client, verifier=None, now=now)
    assert first["complete"] is False
    assert load_source_progress("cninfo")["000001"]["next_page"] == 2
    second = run_serenity_once(symbols=["000001"], client=client, verifier=None, now=now)
    assert second["complete"] is True
    assert client.start_pages == [1, 2]
    assert load_source_progress("cninfo") == {}


def test_backlog_checkpoint_is_not_reused_on_the_next_target_day(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "next-day-backlog"))
    client = _BacklogClient()
    first_day = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)
    next_day = datetime(2026, 7, 11, 8, 0, tzinfo=timezone.utc)

    first = run_serenity_once(
        symbols=["000001"], client=client, verifier=None, now=first_day
    )
    second = run_serenity_once(
        symbols=["000001"], client=client, verifier=None, now=next_day
    )

    assert first["complete"] is False
    assert second["complete"] is True
    assert client.start_pages == [1, 1]


class _SchemaFailureClient(_EmptyRealClient):
    def fetch_symbol(self, symbol, org_id, *, start, end, start_page=1):
        self.request_count += 1
        raise SourceError("schema_changed", schema_error=True)


def test_injected_schema_failure_cannot_poison_live_breaker(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    client = _SchemaFailureClient()
    now = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)
    first = run_serenity_once(symbols=["000001"], client=client, verifier=None, now=now)
    assert first["complete"] is False
    second = run_serenity_once(symbols=["000001"], client=client, verifier=None, now=now)
    assert second["status"] != "circuit_open"


class _RateLimitedDefaultClient(_EmptyRealClient):
    def fetch_symbol(self, symbol, org_id, *, start, end, start_page=1):
        self.request_count += 1
        raise SourceError("rate_limited", status_code=429, retry_after=900)


def test_real_rate_limit_is_persisted_across_worker_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "rate-limit"))
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.CNInfoClient",
        lambda **kwargs: _RateLimitedDefaultClient(),
    )
    now = datetime.now(timezone.utc)
    first = run_serenity_once(symbols=["000001"], now=now)
    assert first["status"] == "failed"
    second = run_serenity_once(symbols=["000001"], now=now)
    assert second["status"] == "circuit_open"
    assert second["reason"] == "cninfo_rate_limited"


class _RateLimitedWithoutHeaderDefaultClient(_EmptyRealClient):
    def fetch_symbol(self, symbol, org_id, *, start, end, start_page=1):
        self.request_count += 1
        raise SourceError("rate_limited", status_code=429, retry_after=None)


def test_real_rate_limit_without_retry_after_is_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "rate-limit-no-header"))
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.CNInfoClient",
        lambda **kwargs: _RateLimitedWithoutHeaderDefaultClient(),
    )
    now = datetime.now(timezone.utc)
    assert run_serenity_once(symbols=["000001"], now=now)["status"] == "failed"
    restarted = run_serenity_once(symbols=["000001"], now=now)
    assert restarted["status"] == "circuit_open"
    assert restarted["reason"] == "cninfo_rate_limited"


class _RateLimitedAfterFirstSymbolDefaultClient(_EmptyRealClient):
    def load_stock_map(self):
        self.request_count += 1
        return {
            "000001": {"org_id": "gssz0000001"},
            "000002": {"org_id": "gssz0000002"},
        }

    def fetch_symbol(self, symbol, org_id, *, start, end, start_page=1):
        self.request_count += 1
        if symbol == "000002":
            raise SourceError("rate_limited", status_code=429, retry_after=None)
        return {
            "records": [],
            "complete": True,
            "backlog": False,
            "schema_fingerprint": "schema",
        }


def test_rate_limit_after_partial_success_remains_source_incomplete(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "partial-rate-limit"))
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.CNInfoClient",
        lambda **kwargs: _RateLimitedAfterFirstSymbolDefaultClient(),
    )
    now = datetime.now(timezone.utc)

    result = run_serenity_once(symbols=["000001", "000002"], now=now)

    assert result["status"] == "partial"
    assert result["complete"] is False
    restarted = run_serenity_once(symbols=["000001", "000002"], now=now)
    assert restarted["status"] == "circuit_open"
    assert restarted["reason"] == "cninfo_rate_limited"


class _StableSchemaDefaultClient(_EmptyRealClient):
    def load_stock_map(self):
        self.request_count += 1
        return {
            "000001": {"org_id": "gssz0000001"},
            "000002": {"org_id": "gssz0000002"},
        }


def test_schema_fingerprint_is_independent_of_target_count(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "schema-target-count"))
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.CNInfoClient",
        lambda **kwargs: _StableSchemaDefaultClient(),
    )
    now = datetime.now(timezone.utc)
    assert run_serenity_once(symbols=["000001"], now=now)["complete"] is True
    expanded = run_serenity_once(symbols=["000001", "000002"], now=now)
    assert expanded["complete"] is True
    assert not any("schema_fingerprint_changed" in item for item in expanded["errors"])


class _HydrationRetryDefaultClient(_EmptyRealClient):
    def __init__(self):
        self.request_count = 0
        self.download_attempts = 0
        self.windows = []

    def fetch_symbol(self, symbol, org_id, *, start, end, start_page=1):
        self.request_count += 1
        self.windows.append((start, end, start_page))
        return {
            "records": [
                {
                    "source": "cninfo",
                    "source_record_id": "hydration-retry",
                    "symbol": symbol,
                    "name": "测试",
                    "org_id": org_id,
                    "title": "2026年半年度业绩预告",
                    "published_at": "2026-07-10T00:00:00+08:00",
                    "source_url": "https://static.cninfo.com.cn/hydration-retry.pdf",
                    "announcement_type": "",
                    "raw_metadata": {"announcementId": "hydration-retry"},
                }
            ],
            "complete": True,
            "backlog": False,
            "schema_fingerprint": "schema",
        }

    def download_pdf(self, url, *, max_bytes):
        self.request_count += 1
        self.download_attempts += 1
        if self.download_attempts == 1:
            raise SourceError("transient_pdf_failure")
        return b"%PDF-real-bytes"


class _AlwaysVerify:
    def verify(self, record, *, start, end):
        return True


def test_hydration_failure_keeps_window_pending_until_retry(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "hydration-retry"))
    client = _HydrationRetryDefaultClient()
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.CNInfoClient",
        lambda **kwargs: client,
    )
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.ExchangeVerifier",
        lambda **kwargs: _AlwaysVerify(),
    )
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.extract_pdf_text",
        lambda data: ("证券代码000001，预计净利润同比增长35%。", "parsed"),
    )
    now = datetime.now(timezone.utc)

    first = run_serenity_once(symbols=["000001"], now=now)
    assert first["complete"] is False
    assert first["status"] == "partial"
    assert first["coverage"][0]["hydration_complete"] is False
    assert load_source_progress("cninfo")["000001"]["status"] == "hydration_backlog"

    second = run_serenity_once(symbols=["000001"], now=now)
    assert second["complete"] is True
    assert load_source_progress("cninfo") == {}
    assert client.windows[0] == client.windows[1]


def test_partial_target_failure_does_not_advance_source_cursor(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "partial-target"))
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.CNInfoClient",
        lambda **kwargs: _EmptyRealClient(),
    )
    now = datetime.now(timezone.utc)

    result = run_serenity_once(symbols=["000001", "000002"], now=now)

    assert result["complete"] is False
    assert result["status"] == "partial"
    cursor = load_cursor("cninfo")
    assert cursor == {}


class _TerminalUnparsedDefaultClient(_HydrationRetryDefaultClient):
    def download_pdf(self, url, *, max_bytes):
        self.request_count += 1
        self.download_attempts += 1
        return b"%PDF-scanned-image-only"


@pytest.mark.parametrize(
    ("extracted_text", "extraction_status"),
    (("", "unparsed"), ("只提取到部分页面", "truncated")),
)
def test_incomplete_pdf_extraction_keeps_target_pending(
    monkeypatch, tmp_path, extracted_text, extraction_status
):
    monkeypatch.setenv(
        "GP_SERENITY_STORE_DIR", str(tmp_path / f"pending-{extraction_status}")
    )
    client = _TerminalUnparsedDefaultClient()
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.CNInfoClient",
        lambda **kwargs: client,
    )
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.ExchangeVerifier",
        lambda **kwargs: _AlwaysVerify(),
    )
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.extract_pdf_text",
        lambda data: (extracted_text, extraction_status),
    )

    first = run_serenity_once(
        symbols=["000001"],
        now=datetime.now(timezone.utc),
    )
    second = run_serenity_once(
        symbols=["000001"],
        now=datetime.now(timezone.utc),
    )

    assert first["complete"] is False
    assert first["status"] == "partial"
    assert first["coverage"][0]["hydration_complete"] is False
    assert load_source_progress("cninfo")["000001"]["status"] == "hydration_backlog"
    assert second["complete"] is False
    assert client.download_attempts == 2


class _ChangingSchemaDefaultClient(_EmptyRealClient):
    fingerprints = ["schema-a", "schema-b"]

    def fetch_symbol(self, symbol, org_id, *, start, end, start_page=1):
        self.request_count += 1
        return {
            "records": [],
            "complete": True,
            "backlog": False,
            "schema_fingerprint": self.fingerprints.pop(0),
        }


def test_schema_fingerprint_change_fails_closed_and_opens_breaker(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "schema-drift"))
    _ChangingSchemaDefaultClient.fingerprints = ["schema-a", "schema-b"]
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.CNInfoClient",
        lambda **kwargs: _ChangingSchemaDefaultClient(),
    )
    now = datetime.now(timezone.utc)
    assert run_serenity_once(symbols=["000001"], now=now)["complete"] is True
    drift = run_serenity_once(symbols=["000001"], now=now)
    assert drift["complete"] is False
    assert any("schema_fingerprint_changed" in error for error in drift["errors"])
    assert run_serenity_once(symbols=["000001"], now=now)["status"] == "circuit_open"
