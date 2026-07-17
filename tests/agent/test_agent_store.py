from __future__ import annotations

import json
from hashlib import sha256
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest

from gp_assistant.agent_store import AgentStore, SnapshotIntegrityError
from gp_assistant.chat_agent import run_chat_turn
from gp_assistant.decision_engine.serenity_policy import (
    build_reference_snapshot,
    counterfactual_arm_checksum,
)
from gp_assistant.contracts.objects import (
    AdvicePick,
    BoardEntry,
    DayBook,
    LiveSlotArtifact,
    MarketBook,
    SlotDataQuality,
    SlotGate,
    TrackedUniverse,
    TurnFrame,
)
from gp_assistant.core.errors import APIError
from gp_assistant.serenity.models import (
    FrozenSerenitySignal,
    NATIVE_SERENITY_FORMULA_VERSION,
)
from gp_assistant.serenity.store import (
    candidate_target_identity_hash,
    serenity_batch_semantic_revision,
)
from gp_assistant.runtime.producer import producer_metadata


def make_book(
    snapshot_id: str = "snapshot-1",
    *,
    decision_trade_day: str = "2026-07-13",
    daybook_effective_day: str = "2026-07-13",
) -> MarketBook:
    target_hash = candidate_target_identity_hash(
        ["600519"],
        decision_trade_day=decision_trade_day,
        daybook_effective_day=daybook_effective_day,
    )
    target_id = "sertarget_" + target_hash[:24]
    source_run_id = "serpoll_test"
    readiness_revision = "readiness-test"
    activation_observed_at = "2026-07-13T09:00:00+08:00"
    activation_revision = "seractivation_test"
    poll_finished_at = "2026-07-13T09:30:00+08:00"
    poll_expires_at = "2026-07-13T17:30:00+08:00"
    signal_decision_at = "2026-07-13T10:00:00+08:00"
    decision_context_snapshot_id = "dctx_test_snapshot_1"
    lineage = {
        "target_id": target_id,
        "source_run_id": source_run_id,
        "readiness_revision": readiness_revision,
        "activation_observed_at": activation_observed_at,
        "activation_revision": activation_revision,
        "poll_finished_at": poll_finished_at,
        "poll_expires_at": poll_expires_at,
        "facts": {},
    }
    expert_scores = {
        "signal": 0.9,
        "memory": 0.8,
        "probability": 0.8,
        "risk": 0.2,
        "setup": 0.8,
        "ranking": 0.8,
        "regime": 0.8,
        "exploration": 0.2,
        "serenity": 0.0,
    }
    expert_weights = {
        "signal": 0.16,
        "memory": 0.14,
        "probability": 0.20,
        "risk": 0.16,
        "setup": 0.14,
        "ranking": 0.12,
        "regime": 0.05,
        "exploration": 0.03,
    }
    expert_contributions = {
        key: (-1.0 if key == "risk" else 1.0)
        * expert_weights[key]
        * expert_scores[key]
        for key in expert_weights
    }
    expert_contributions["serenity"] = 0.0
    decision_score = sum(expert_contributions.values())
    signal_input_hash = sha256(
        json.dumps(
            {
                "symbol": "600519",
                "decision_at": signal_decision_at,
                "target_id": target_id,
                "status": "no_relevant_evidence",
                "alpha_value": 0.0,
                "facts": [],
                "lineage": lineage,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    adaptive = {
        "adaptive_score": decision_score,
        "baseline_adaptive_score": decision_score,
        "decision_score": decision_score,
        "expert_scores": expert_scores,
        "expert_weights": expert_weights,
        "expert_contributions": expert_contributions,
        "serenity_status": "no_relevant_evidence",
        "serenity_policy_state": "shadow",
        "serenity_weight": 0.0,
        "serenity_alpha_value": 0.0,
        "serenity_adjustment": 0.0,
        "serenity_fact_ids": [],
        "serenity_learning_eligible": False,
        "serenity_target_id": target_id,
        "serenity_source_run_id": source_run_id,
        "serenity_input_hash": signal_input_hash,
        "serenity_lineage": lineage,
        "serenity_non_binding": True,
    }
    serenity = {
        "status": "no_relevant_evidence",
        "policy_state": "shadow",
        "effective_weight": 0.0,
        "alpha_value": 0.0,
        "score_contribution": 0.0,
        "decision_score": decision_score,
        "fact_ids": [],
        "facts": [],
        "learning_eligible": False,
        "target_id": target_id,
        "source_run_id": source_run_id,
        "input_hash": signal_input_hash,
        "lineage": lineage,
        "non_binding": True,
    }
    pick = AdvicePick(
        symbol="600519",
        name="贵州茅台",
        rank=1,
        thesis="强势延续",
        entry_plan={"price": 100},
        stop_plan={"price": 90},
        take_profit_plan={"price": 110},
        scores={
            "final": decision_score,
            "adaptive": decision_score,
            "serenity_adjustment": 0.0,
            "serenity_alpha": 0.0,
        },
        why_selected="评分第一",
        risk_flags=["波动风险"],
        evidence_refs=["evidence:600519"],
        meta={
            "serenity": serenity,
            "adaptive_policy": adaptive,
            "expert_scores": expert_scores,
            "expert_weights": expert_weights,
            "expert_contributions": expert_contributions,
        },
        explain_context={"serenity": serenity},
        decision_context_snapshot_id=decision_context_snapshot_id,
    )
    entry = BoardEntry(
        symbol="600519",
        name="贵州茅台",
        rank=1,
        final_score=decision_score,
        live_score=0.8,
        execution_state="watch",
        can_open=True,
        stretched=False,
        invalidated=False,
        summary="趋势与流动性符合当前策略",
        pick=pick,
        explain_context={"serenity": serenity},
    )
    target = {
        "target_id": target_id,
        "decision_trade_day": decision_trade_day,
        "daybook_effective_day": daybook_effective_day,
        "observed_at": "2026-07-13T09:00:00+08:00",
        "symbols": ["600519"],
        "input_hash": target_hash,
        "created_at": "2026-07-13T09:00:00+08:00",
        "activated_at": activation_observed_at,
        "activation_observed_at": activation_observed_at,
        "activation_revision": activation_revision,
    }
    policy = {
        "formula_version": NATIVE_SERENITY_FORMULA_VERSION,
        "mode": "native",
        "state": "shadow",
        "epoch": 1,
        "applied_weight": 0.0,
        "max_weight": 0.08,
        "native_required": True,
        "baseline_selected_symbols": ["600519"],
        "applied_selected_symbols": ["600519"],
        "would_change_topk": False,
    }
    semantic_signal = FrozenSerenitySignal(
        symbol="600519",
        status="no_relevant_evidence",
        availability=0,
        learning_eligible=False,
        direction=0,
        confidence=0.0,
        source_quality=0.0,
        alpha_value=0.0,
        decision_at=signal_decision_at,
        generated_at=signal_decision_at,
        target_id=target_id,
        source_run_id=source_run_id,
        evidence_count=0,
        fact_ids=[],
        facts=[],
        lineage=lineage,
        input_hash=signal_input_hash,
    )
    semantic_revision = serenity_batch_semantic_revision(
        {"600519": semantic_signal},
        target_id=target_id,
        target_input_hash=target_hash,
        activation_observed_at=activation_observed_at,
        activation_revision=activation_revision,
        formula_version=NATIVE_SERENITY_FORMULA_VERSION,
        policy_snapshot=policy,
    )
    attestation_candidate = {
        "symbol": "600519",
        "scored": True,
        "status": "no_relevant_evidence",
        "target_id": target_id,
        "source_run_id": source_run_id,
        "readiness_revision": readiness_revision,
        "semantic_revision": semantic_revision,
        "poll_finished_at": poll_finished_at,
        "poll_expires_at": poll_expires_at,
        "input_hash": signal_input_hash,
        "decision_at": signal_decision_at,
        "lineage": lineage,
        "availability": 0,
        "direction": 0,
        "confidence": 0.0,
        "source_quality": 0.0,
        "evidence_count": 0,
        "fact_ids": [],
        "facts": [],
        "learning_eligible": False,
        "alpha_value": 0.0,
        "policy_state": "shadow",
        "effective_weight": 0.0,
        "score_contribution": 0.0,
        "baseline_adaptive_score": decision_score,
        "decision_score": decision_score,
        "expert_scores": expert_scores,
        "expert_weights": expert_weights,
        "expert_contributions": expert_contributions,
        "non_binding": True,
    }
    attestation = {
        "schema": "SerenityNativeAttestation.v1",
        "formula_version": NATIVE_SERENITY_FORMULA_VERSION,
        "target_id": target_id,
        "target_input_hash": target_hash,
        "activation_observed_at": activation_observed_at,
        "activation_revision": activation_revision,
        "source_run_id": source_run_id,
        "readiness_revision": readiness_revision,
        "semantic_revision": semantic_revision,
        "poll_finished_at": poll_finished_at,
        "poll_expires_at": poll_expires_at,
        "policy_snapshot": policy,
        "topk": 1,
        "decision": "recommend",
        "decision_context_snapshot_id": decision_context_snapshot_id,
        "ranked_symbols": ["600519"],
        "selected_symbols": ["600519"],
        "candidates": {"600519": attestation_candidate},
    }
    source_meta = {
        "topk": 1,
        "reserve_count": 0,
        "selection_policy": "adaptive_v2_native_serenity_single_score",
        "serenity_target_id": target_id,
        "serenity_candidate_target": target,
        "serenity_native_ready": True,
        "serenity_formula_version": NATIVE_SERENITY_FORMULA_VERSION,
        "serenity_policy_snapshot": policy,
        "serenity_source_run_id": source_run_id,
        "serenity_readiness_revision": readiness_revision,
        "serenity_semantic_revision": semantic_revision,
        "serenity_poll_finished_at": poll_finished_at,
        "serenity_poll_expires_at": poll_expires_at,
        "serenity_native_attestation": attestation,
        "decision": "recommend",
        "decision_context_snapshot_id": decision_context_snapshot_id,
    }
    return MarketBook(
        trading_day=decision_trade_day.replace("-", ""),
        book_version=snapshot_id,
        artifact_id=snapshot_id,
        updated_at="2026-07-13T10:00:00+08:00",
        regime={},
        daybook=DayBook(
            trading_day=daybook_effective_day.replace("-", ""),
            generated_at="2026-07-13T09:00:00+08:00",
            tradeable=True,
            picks=[pick],
            source_meta=source_meta,
            producer=producer_metadata(),
        ),
        board=[entry],
        publish_allowed=True,
        gate=SlotGate(state="ALLOW", score=100.0),
        data_quality=SlotDataQuality(
            complete=True,
            freshness_state="fresh",
            symbols_expected=1,
            symbols_received=1,
            benchmark_received=True,
        ),
    )


def make_pending_runtime(
    artifact_id: str = "pending-artifact-1",
    *,
    observed_at: str = "2026-07-13T10:00:00+08:00",
) -> tuple[DayBook, LiveSlotArtifact, SimpleNamespace]:
    decision_context_snapshot_id = "dcs_" + "a" * 24
    policy = {
        "formula_version": NATIVE_SERENITY_FORMULA_VERSION,
        "mode": "native",
        "state": "warming",
        "epoch": 1,
        "applied_weight": 0.0,
        "max_weight": 0.08,
        "native_required": True,
        "baseline_selected_symbols": [],
        "applied_selected_symbols": [],
        "would_change_topk": False,
    }
    decision_snapshot = {
        "schema": "DecisionContextSnapshot.v1",
        "snapshot_id": decision_context_snapshot_id,
        "run_id": "market_memory_pending_test",
        "as_of": "2026-07-13",
        "decision_trade_day": "2026-07-13",
        "daybook_effective_day": "2026-07-13",
        "observed_at": observed_at,
        "created_at": observed_at,
        "candidate_list": [],
        "rejected_candidates": [],
        "ranking_output": {"ranked_symbols": []},
        "final_decision": "no_trade",
        "selected_symbols": [],
        "serenity_candidate_target": None,
        "serenity_native_attestation": {},
        "serenity_source_run_id": None,
        "serenity_readiness_revision": None,
        "serenity_semantic_revision": None,
        "serenity_poll_finished_at": None,
        "serenity_poll_expires_at": None,
        "serenity_policy_snapshot": policy,
        "serenity_formula_version": NATIVE_SERENITY_FORMULA_VERSION,
        "serenity_reference_snapshot_id": None,
        "serenity_outcome_risk_plans": {},
    }
    market_time = SimpleNamespace(
        decision_trade_day="2026-07-13",
        daybook_effective_day="2026-07-13",
        pulse_trade_day=None,
        pulse_slot_closed_at=None,
        observed_at=observed_at,
        market_phase="postclose_ready",
        target_mode="previous_completed",
        pending_eod_day=None,
    )
    source_meta = {
        "topk": 10,
        "reserve_count": 2,
        "selection_policy": "adaptive_v2_native_serenity_single_score",
        "decision_context_snapshot_id": decision_context_snapshot_id,
        "serenity_reference_snapshot_id": None,
        "serenity_candidate_target": {},
        "serenity_native_ready": False,
        "serenity_formula_version": NATIVE_SERENITY_FORMULA_VERSION,
        "serenity_policy_snapshot": policy,
        "serenity_native_attestation": {},
        "decision": "no_trade",
        "market_time": {
            "decision_trade_day": market_time.decision_trade_day,
            "daybook_effective_day": market_time.daybook_effective_day,
            "observed_at": observed_at,
        },
        "_deferred_persistence": {
            "decision_snapshot": decision_snapshot,
            "serenity_reference_snapshot": None,
            "decision_day": "2026-07-13",
            "epoch": 1,
            "formula_version": NATIVE_SERENITY_FORMULA_VERSION,
        },
    }
    daybook = DayBook(
        trading_day="20260713",
        generated_at=observed_at,
        tradeable=False,
        reason="serenity_coverage_incomplete",
        source_meta=source_meta,
        producer=producer_metadata(),
    )
    artifact = LiveSlotArtifact(
        artifact_id=artifact_id,
        trade_day="20260713",
        market_phase="postclose_ready",
        slot_status="BLOCKED",
        publish_allowed=False,
        daybook_effective_day="20260713",
        gate=SlotGate(state="BLOCKED", reasons=["serenity_coverage_incomplete"]),
        data_quality=SlotDataQuality(complete=True, freshness_state="fresh"),
        created_at=observed_at,
        updated_at=observed_at,
        producer=producer_metadata(),
    )
    return daybook, artifact, market_time


def make_ready_runtime(
    artifact_id: str = "ready-artifact-1",
) -> tuple[DayBook, LiveSlotArtifact, SimpleNamespace]:
    observed_at = "2026-07-13T10:00:00+08:00"
    decision_context_snapshot_id = "dcs_" + "b" * 24
    book = make_book(artifact_id)
    daybook = book.daybook.model_copy(deep=True)
    board = [entry.model_copy(deep=True) for entry in book.board]
    meta = daybook.source_meta
    meta["decision_context_snapshot_id"] = decision_context_snapshot_id
    attestation = dict(meta["serenity_native_attestation"])
    attestation["decision_context_snapshot_id"] = decision_context_snapshot_id
    meta["serenity_native_attestation"] = attestation
    for pick in [*daybook.picks, *daybook.reserve_picks]:
        pick.decision_context_snapshot_id = decision_context_snapshot_id
    for entry in board:
        entry.pick.decision_context_snapshot_id = decision_context_snapshot_id

    candidate_record = dict(attestation["candidates"]["600519"])
    signal = FrozenSerenitySignal(
        symbol="600519",
        status="no_relevant_evidence",
        availability=0,
        learning_eligible=False,
        direction=0,
        confidence=0.0,
        source_quality=0.0,
        alpha_value=0.0,
        decision_at=observed_at,
        generated_at=observed_at,
        target_id=str(candidate_record["target_id"]),
        source_run_id=str(candidate_record["source_run_id"]),
        fact_ids=[],
        facts=[],
        lineage=dict(candidate_record["lineage"]),
        input_hash=str(candidate_record["input_hash"]),
    )
    score = float(candidate_record["decision_score"])
    arms = []
    for step in range(9):
        arm = {
            "weight": step / 100,
            "ranked_symbols": ["600519"],
            "selected_symbols": ["600519"],
            "scores": {"600519": score},
        }
        arm["checksum"] = counterfactual_arm_checksum(arm)
        arms.append(arm)
    policy = dict(meta["serenity_policy_snapshot"])
    reference = build_reference_snapshot(
        decision_context_snapshot_id=decision_context_snapshot_id,
        decision_day="2026-07-13",
        decision_at=observed_at,
        adaptive_output={
            "serenity_policy": policy,
            "serenity_counterfactuals": arms,
            "serenity_reference_counterfactuals": [],
        },
        signals={"600519": signal},
        risk_plans={
            "600519": {
                "entry": dict(daybook.picks[0].entry_plan),
                "stop": dict(daybook.picks[0].stop_plan),
                "take_profit": dict(daybook.picks[0].take_profit_plan),
            }
        },
    )
    meta["serenity_reference_snapshot_id"] = reference.snapshot_id
    meta["market_time"] = {
        "decision_trade_day": "2026-07-13",
        "daybook_effective_day": "2026-07-13",
        "observed_at": observed_at,
    }
    decision_snapshot = {
        "schema": "DecisionContextSnapshot.v1",
        "snapshot_id": decision_context_snapshot_id,
        "run_id": "market_memory_ready_test",
        "as_of": "2026-07-13",
        "decision_trade_day": "2026-07-13",
        "daybook_effective_day": "2026-07-13",
        "observed_at": observed_at,
        "created_at": observed_at,
        "candidate_list": [{"symbol": "600519"}],
        "rejected_candidates": [],
        "ranking_output": {"ranked_symbols": ["600519"]},
        "final_decision": "recommend",
        "selected_symbols": ["600519"],
        "serenity_candidate_target": dict(meta["serenity_candidate_target"]),
        "serenity_native_attestation": attestation,
        "serenity_source_run_id": meta["serenity_source_run_id"],
        "serenity_readiness_revision": meta["serenity_readiness_revision"],
        "serenity_semantic_revision": meta["serenity_semantic_revision"],
        "serenity_poll_finished_at": meta["serenity_poll_finished_at"],
        "serenity_poll_expires_at": meta["serenity_poll_expires_at"],
        "serenity_policy_snapshot": policy,
        "serenity_formula_version": NATIVE_SERENITY_FORMULA_VERSION,
        "serenity_counterfactuals": arms,
        "serenity_reference_counterfactuals": [],
        "serenity_reference_snapshot_id": reference.snapshot_id,
        "serenity_outcome_risk_plans": dict(reference.risk_plans),
    }
    meta["_deferred_persistence"] = {
        "decision_snapshot": decision_snapshot,
        "serenity_reference_snapshot": reference.model_dump(mode="json"),
        "decision_day": "2026-07-13",
        "epoch": 1,
        "formula_version": NATIVE_SERENITY_FORMULA_VERSION,
    }
    market_time = SimpleNamespace(
        decision_trade_day="2026-07-13",
        daybook_effective_day="2026-07-13",
        pulse_trade_day=None,
        pulse_slot_closed_at=None,
        observed_at=observed_at,
        market_phase="postclose_ready",
        target_mode="previous_completed",
        pending_eod_day=None,
    )
    artifact = LiveSlotArtifact(
        artifact_id=artifact_id,
        trade_day="20260713",
        market_phase="postclose_ready",
        slot_status="READY",
        publish_allowed=True,
        daybook_effective_day="20260713",
        gate=SlotGate(state="ALLOW", score=100.0, buyable_count=1),
        tracked_universe=TrackedUniverse(
            reco=["600519"], total=["600519"]
        ),
        board=board,
        data_quality=SlotDataQuality(
            complete=True,
            freshness_state="fresh",
            symbols_expected=1,
            symbols_received=1,
            benchmark_received=True,
        ),
        created_at=observed_at,
        updated_at=observed_at,
        producer=producer_metadata(),
    )
    return daybook, artifact, market_time


def fake_parse_turn_frame(context, user_message):
    symbol = "600519" if "600519" in user_message else None
    request = "pick_detail" if symbol or "为什么" in user_message else "recommend"
    return TurnFrame(
        frame_id="frame-test",
        raw_message=user_message,
        subject="symbol" if symbol else "run",
        request=request,
        freshness="active_run",
        references={"symbol": symbol} if symbol else {},
        constraints={"topk": 3, "allow_derived_data": True},
        ambiguity={"confidence": 1.0, "notes": [], "needs_clarification": False},
    )


def fake_render_reply(payload):
    details = payload["tool_evidence_context"].get("candidate_details") or []
    if details:
        return f"基于当前不可变快照，{details[0]['symbol']} 是当前候选；请严格遵守既定买入区间、止损与目标。"
    return "基于当前不可变快照，本次没有可执行标的；请等待下一次完整决策。"


def patch_chat_llm(monkeypatch):
    monkeypatch.setattr("gp_assistant.chat_agent.parse_turn_frame", fake_parse_turn_frame)
    monkeypatch.setattr("gp_assistant.chat_agent.render_reply", fake_render_reply)
    monkeypatch.setattr(
        "gp_assistant.chat_agent._current_market_time_state",
        lambda _snapshot: {"matches": True, "revision": "market-test"},
    )
    monkeypatch.setattr(
        "gp_assistant.chat_agent._current_serenity_check",
        lambda _book: (
            None,
            {
                "semantic_revision": "serenity-semantic-test",
                "binding_token": "serenity-test",
                "available": True,
            },
        ),
    )
    monkeypatch.setattr(
        "gp_assistant.chat_agent.current_llm_call_trace",
        lambda: [
            {"stage": "intent_routing", "success": True, "http_status": 200, "request_model": "test-model", "response_model": "test-model", "response_id": "route-test"},
            {"stage": "tool_evidence", "success": True, "http_status": 200, "request_model": "test-model", "response_model": "test-model", "response_id": "narrate-test"},
        ],
    )


def test_snapshot_is_immutable_and_pointer_is_valid(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    first = store.publish_book(make_book())
    assert store.current_snapshot().snapshot_id == first.snapshot_id
    altered = make_book()
    altered.daybook.picks[0].why_selected = "被篡改"
    with pytest.raises(SnapshotIntegrityError, match="immutable"):
        store.publish_book(altered)


def test_runtime_publication_commits_pointer_last_and_reuses_bound_daybook(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "market-memory"))
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    store = AgentStore(tmp_path / "agent.db")
    daybook, artifact, market_time = make_pending_runtime()

    first = store.publish_runtime_artifact(
        daybook, artifact, market_time=market_time
    )
    assert store.current_snapshot().snapshot_id == first.snapshot_id
    persisted = store.load_daybook("2026-07-13", producer=producer_metadata())
    assert persisted is not None
    assert "_deferred_persistence" not in persisted.source_meta
    binding = dict(persisted.source_meta["runtime_evidence_binding"])
    assert binding["schema"] == "RuntimeEvidenceBinding.v1"
    assert binding["serenity_reference_snapshot_id"] is None

    later = "2026-07-13T10:05:00+08:00"
    second_artifact = artifact.model_copy(
        update={
            "artifact_id": "pending-artifact-2",
            "updated_at": later,
        }
    )
    second_market_time = SimpleNamespace(**vars(market_time))
    second_market_time.observed_at = later
    second = store.publish_runtime_artifact(
        persisted,
        second_artifact,
        market_time=second_market_time,
    )
    assert second.snapshot_id == "pending-artifact-2"
    assert store.current_snapshot().snapshot_id == second.snapshot_id


def test_runtime_sidecar_failure_keeps_previous_current_pointer(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "market-memory"))
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    store = AgentStore(tmp_path / "agent.db")
    old = store.publish_book(make_book("old-current"))
    daybook, artifact, market_time = make_pending_runtime()

    def fail_decision(_snapshot):
        raise RuntimeError("decision-sidecar-failed")

    monkeypatch.setattr(store, "_persist_decision_snapshot", fail_decision)
    with pytest.raises(RuntimeError, match="decision-sidecar-failed"):
        store.publish_runtime_artifact(
            daybook, artifact, market_time=market_time
        )
    assert store.current_snapshot().snapshot_id == old.snapshot_id
    assert store.load_snapshot(artifact.artifact_id) is None


def test_runtime_final_agent_transaction_failure_rolls_back_visibility(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "market-memory"))
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    store = AgentStore(tmp_path / "agent.db")
    old = store.publish_book(make_book("old-current"))
    daybook, artifact, market_time = make_pending_runtime()

    def fail_pointer(_conn, _snapshot_id):
        raise RuntimeError("pointer-commit-failed")

    monkeypatch.setattr(store, "_advance_current_snapshot", fail_pointer)
    with pytest.raises(RuntimeError, match="pointer-commit-failed"):
        store.publish_runtime_artifact(
            daybook, artifact, market_time=market_time
        )
    assert store.current_snapshot().snapshot_id == old.snapshot_id
    assert store.load_snapshot(artifact.artifact_id) is None
    assert store.load_daybook("2026-07-13", producer=producer_metadata()) is None


def test_runtime_evidence_mismatch_is_rejected_before_any_sidecar_write(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "market-memory"))
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    store = AgentStore(tmp_path / "agent.db")
    daybook, artifact, market_time = make_pending_runtime()
    daybook.source_meta["_deferred_persistence"]["decision_snapshot"][
        "selected_symbols"
    ] = ["600519"]
    writes = []
    monkeypatch.setattr(
        store,
        "_persist_decision_snapshot",
        lambda snapshot: writes.append(snapshot) or snapshot["snapshot_id"],
    )

    with pytest.raises(
        SnapshotIntegrityError, match="runtime_decision_snapshot_result_mismatch"
    ):
        store.publish_runtime_artifact(
            daybook, artifact, market_time=market_time
        )
    assert writes == []
    assert store.current_snapshot() is None


def test_ready_runtime_persists_decision_reference_pending_before_visibility(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "market-memory"))
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    store = AgentStore(tmp_path / "agent.db")
    daybook, artifact, market_time = make_ready_runtime()

    record = store.publish_runtime_artifact(
        daybook, artifact, market_time=market_time
    )
    binding = dict(
        store.book_for_snapshot(record).daybook.source_meta[
            "runtime_evidence_binding"
        ]
    )
    from gp_assistant.market_memory.store import load_decision_snapshot
    from gp_assistant.serenity.store import (
        load_pending_evaluation,
        load_reference_snapshot,
    )

    assert load_decision_snapshot(binding["decision_context_snapshot_id"])
    assert load_reference_snapshot(binding["serenity_reference_snapshot_id"])
    assert load_pending_evaluation(binding["serenity_pending_id"])
    assert store.current_snapshot().snapshot_id == artifact.artifact_id


def test_serenity_sidecar_failure_keeps_previous_current_pointer(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "market-memory"))
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    store = AgentStore(tmp_path / "agent.db")
    old = store.publish_book(make_book("old-current"))
    daybook, artifact, market_time = make_ready_runtime()

    def fail_serenity(*_args, **_kwargs):
        raise RuntimeError("serenity-sidecar-failed")

    monkeypatch.setattr(store, "_persist_serenity_reference", fail_serenity)
    with pytest.raises(RuntimeError, match="serenity-sidecar-failed"):
        store.publish_runtime_artifact(
            daybook, artifact, market_time=market_time
        )
    assert store.current_snapshot().snapshot_id == old.snapshot_id
    assert store.load_snapshot(artifact.artifact_id) is None


def test_decision_snapshot_file_is_safe_and_recovers_from_partial_json(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "market-memory"))
    from gp_assistant.market_memory.store import (
        decision_snapshot_path,
        load_decision_snapshot,
        save_decision_snapshot,
    )

    snapshot = {
        "snapshot_id": "dcs_" + "c" * 24,
        "run_id": "run-safe-file",
        "as_of": "2026-07-13",
        "decision_trade_day": "2026-07-14",
        "final_decision": "no_trade",
    }
    assert save_decision_snapshot(snapshot) == snapshot["snapshot_id"]
    path = decision_snapshot_path(snapshot["snapshot_id"])
    path.write_text("{", encoding="utf-8")
    assert load_decision_snapshot(snapshot["snapshot_id"]) == snapshot
    assert save_decision_snapshot(snapshot) == snapshot["snapshot_id"]
    assert json.loads(path.read_text(encoding="utf-8")) == snapshot
    with pytest.raises(ValueError, match="decision_snapshot_id_invalid"):
        save_decision_snapshot({"snapshot_id": "../escape", "as_of": "x"})


def test_turn_commit_is_atomic_idempotent_and_integrity_checked(tmp_path, monkeypatch):
    patch_chat_llm(monkeypatch)
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())
    first = run_chat_turn(session_id="s1", client_turn_id="c1", user_message="推荐", store=store)
    retried = run_chat_turn(session_id="s1", client_turn_id="c1", user_message="推荐", store=store)
    assert retried == first
    assert [(turn["seq"], turn["role"]) for turn in store.session_turns("s1")] == [(1, "user"), (2, "assistant")]
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_concurrent_distinct_turns_have_no_duplicate_sequence(tmp_path, monkeypatch):
    patch_chat_llm(monkeypatch)
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda index: run_chat_turn(session_id="s1", client_turn_id=f"c{index}", user_message="推荐", store=store), range(4)))
    assert {result["client_turn_id"] for result in results} == {"c0", "c1", "c2", "c3"}
    assert [turn["seq"] for turn in store.session_turns("s1")] == list(range(1, 9))


def test_missing_snapshot_returns_structured_no_trade_without_legacy_read(tmp_path):
    with pytest.raises(APIError) as caught:
        run_chat_turn(session_id="new", client_turn_id="c1", user_message="推荐", store=AgentStore(tmp_path / "agent.db"))
    assert caught.value.status_code == 503
    assert caught.value.detail == {"reason": "current_snapshot_unavailable"}


def test_follow_up_remains_bound_to_first_session_snapshot(tmp_path, monkeypatch):
    patch_chat_llm(monkeypatch)
    store = AgentStore(tmp_path / "agent.db")
    store.publish_book(make_book("snapshot-1"))
    first = run_chat_turn(session_id="s1", client_turn_id="c1", user_message="推荐", store=store)
    store.publish_book(make_book("snapshot-2"))
    second = run_chat_turn(session_id="s1", client_turn_id="c2", user_message="600519 为什么", store=store)
    assert first["snapshot_id"] == second["snapshot_id"] == "snapshot-1"
