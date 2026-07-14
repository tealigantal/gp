import json
import sqlite3
from datetime import date
from types import SimpleNamespace

import pytest

from gp_assistant.decision_engine.serenity_policy import build_reference_snapshot
from gp_assistant.core.config import SerenityConfig, load_config
from gp_assistant.serenity.models import (
    FrozenSerenitySignal,
    NATIVE_SERENITY_FORMULA_VERSION,
    SerenityFact,
    SerenityHypothesis,
    SerenityPolicyState,
)
from gp_assistant.serenity.store import (
    candidate_target_ready,
    candidate_target_readiness_revision,
    commit_evaluation_result,
    commit_poll,
    current_native_readiness_state,
    acquire_worker_lease,
    enqueue_pending_evaluation,
    ensure_native_formula_epoch,
    evidence_db_path,
    initialize_store,
    list_pending_evaluations,
    list_evaluations,
    load_latest_candidate_target,
    load_policy_state,
    load_frozen_signals,
    lookup_document,
    record_bootstrap_run,
    publish_candidate_target,
    save_reference_and_enqueue_pending,
    save_policy_state,
    save_policy_state_with_ledger,
    save_evaluation,
    status_snapshot,
)
from gp_assistant.serenity.worker import _record_payload


def _record(first_seen: str, *, content_hash: str = "a" * 64, direction: int = 1):
    doc_id = "serdoc_test"
    version_id = f"server_{content_hash[:8]}"
    fact = SerenityFact(
        fact_id=f"serfact_{content_hash[:8]}",
        symbol="000001",
        fact_type="earnings_guidance",
        claim="公司披露了可量化的业绩方向变化。",
        published_at="2026-07-09T00:00:00+08:00",
        effective_available_at=first_seen,
        source_document_id=doc_id,
        source_version_id=version_id,
        source="cninfo",
        source_url="https://example.test/a.pdf",
        content_sha256=content_hash,
        direction=direction,
        confidence=0.9,
        source_quality=1.0,
        verification_state="verified",
    )
    hyp = SerenityHypothesis(
        hypothesis_id=f"serhyp_{content_hash[:8]}",
        fact_id=fact.fact_id,
        symbol="000001",
        event_type="earnings_guidance",
        claim=fact.claim,
        mechanism="盈利预期改善。",
        direction=direction,
        confidence=0.9,
        source_quality=1.0,
        effective_available_at=first_seen,
        evidence_refs=[fact.fact_id],
        status="verified",
    )
    return {
        "document": {
            "document_id": doc_id,
            "source_record_id": "1225000000",
            "symbol": "000001",
            "title": "业绩预告",
            "source_url": fact.source_url,
            "published_at": fact.published_at,
            "first_seen_at": first_seen,
            "last_seen_at": first_seen,
            "raw_metadata": {"announcementId": "1225000000"},
        },
        "version": {
            "version_id": version_id,
            "content_hash": content_hash,
            "extraction_status": "parsed",
            "evidence": {},
            "created_at": first_seen,
        },
        "facts": [fact],
        "hypotheses": [hyp],
    }


def _commit(record, run_id: str):
    first_seen = record["document"]["first_seen_at"]
    result = commit_poll(
        source="cninfo",
        source_kind="live",
        run={
            "run_id": run_id,
            "started_at": first_seen,
            "finished_at": first_seen,
            "elapsed_sec": 0.2,
            "status": "success",
            "complete": True,
            "request_count": 1,
            "item_count": 1,
            "next_due_at": first_seen,
            "stale_after_sec": 3600,
        },
        records=[record],
        cursor={"latest": "1225000000"},
        schema_fingerprint="schema1",
        coverage=[
            {
                "symbol": "000001",
                "metadata_complete": True,
                "hydration_complete": True,
                "item_count": 1,
                "window_start": "2026-06-10",
                "window_end": "2026-07-10",
            }
        ],
    )
    record_bootstrap_run(
        poll_run_id=run_id,
        source="cninfo",
        symbols=["000001"],
        lookback_days=30,
        complete=True,
        payload={"test": True},
    )
    return result


def _commit_target_poll(
    target,
    *,
    run_id: str,
    finished_at: str,
    records=(),
    schema_fingerprint: str = "schema1",
    window_start: str = "2026-06-10",
    window_end: str = "2026-07-10",
    item_count: int | None = None,
    complete: bool = True,
    status: str = "success",
    stale_after_sec: float = 3600,
):
    resolved_count = len(records) if item_count is None else item_count
    return commit_poll(
        source="cninfo",
        source_kind="live",
        run={
            "run_id": run_id,
            "started_at": finished_at,
            "finished_at": finished_at,
            "elapsed_sec": 0.2,
            "status": status,
            "complete": complete,
            "request_count": 1,
            "item_count": resolved_count,
            "stale_after_sec": stale_after_sec,
            "target_id": target.target_id,
            "target_activation_revision": target.activation_revision,
        },
        records=list(records),
        cursor={} if complete else None,
        schema_fingerprint=schema_fingerprint,
        coverage=[
            {
                "symbol": symbol,
                "metadata_complete": True,
                "hydration_complete": bool(complete),
                "item_count": resolved_count,
                "window_start": window_start,
                "window_end": window_end,
                "checked_at": finished_at,
            }
            for symbol in target.symbols
        ],
    )


def test_append_only_versions_and_first_seen(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    first = "2026-07-10T10:00:00+00:00"
    _commit(_record(first), "run1")
    later = "2026-07-10T11:00:00+00:00"
    _commit(_record(later, content_hash="b" * 64), "run2")
    stored = lookup_document("cninfo", "1225000000")
    assert stored["first_seen_at"] == first
    assert stored["content_hash"] == "b" * 64
    signals = load_frozen_signals(["000001"], decision_at="2026-07-10T12:00:00+00:00")
    assert signals["000001"].status == "available"
    assert signals["000001"].availability == 1
    assert signals["000001"].evidence_count == 1
    assert signals["000001"].direction == 1


def test_superseded_version_facts_do_not_survive_current_document_view(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    first = "2026-07-10T10:00:00+00:00"
    _commit(_record(first), "run1")
    _commit(_record("2026-07-10T11:00:00+00:00", content_hash="b" * 64, direction=-1), "run2")
    signal = load_frozen_signals(["000001"], decision_at="2026-07-10T12:00:00+00:00")["000001"]
    assert signal.evidence_count == 1
    assert signal.direction == -1


def test_factless_latest_version_supersedes_older_facts(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    _commit(_record("2026-07-10T10:00:00+00:00"), "run1")
    correction = _record("2026-07-10T11:00:00+00:00", content_hash="c" * 64)
    correction["facts"] = []
    correction["hypotheses"] = []
    _commit(correction, "run2")

    signal = load_frozen_signals(
        ["000001"], decision_at="2026-07-10T12:00:00+00:00"
    )["000001"]

    assert signal.status == "no_relevant_evidence"
    assert signal.availability == 0
    assert signal.evidence_count == 0
    assert signal.fact_ids == []


def test_initial_withdrawal_never_exposes_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "withdrawn"))
    withdrawn = _record("2026-07-10T10:00:00+00:00")
    withdrawn["document"]["withdrawn"] = True
    _commit(withdrawn, "withdrawn-run")

    signal = load_frozen_signals(
        ["000001"], decision_at="2026-07-10T10:30:00+00:00"
    )["000001"]
    conn = sqlite3.connect(evidence_db_path())
    try:
        withdrawn_at = conn.execute(
            "SELECT withdrawn_at FROM documents WHERE document_id='serdoc_test'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert withdrawn_at == "2026-07-10T10:00:00+00:00"
    assert signal.status == "no_relevant_evidence"
    assert signal.availability == 0
    assert signal.fact_ids == []


def test_active_candidate_target_can_reactivate_an_existing_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "targets"))
    first = publish_candidate_target(
        ["000001"],
        decision_trade_day="2026-07-10",
        daybook_effective_day="2026-07-11",
        observed_at="2026-07-10T10:00:00+00:00",
    )
    publish_candidate_target(
        ["000002"],
        decision_trade_day="2026-07-11",
        daybook_effective_day="2026-07-12",
        observed_at="2026-07-11T10:00:00+00:00",
    )
    reactivated = publish_candidate_target(
        ["000001"],
        decision_trade_day="2026-07-10",
        daybook_effective_day="2026-07-11",
        observed_at="2026-07-12T10:00:00+00:00",
    )

    assert reactivated.target_id == first.target_id
    assert reactivated.observed_at == "2026-07-12T10:00:00+00:00"
    assert reactivated.activation_revision != first.activation_revision
    assert load_latest_candidate_target().target_id == first.target_id


def test_equivalent_complete_polls_renew_freshness_without_changing_semantics(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "semantic-renewal"))
    monkeypatch.setenv("GP_SERENITY_MODE", "native")
    target = publish_candidate_target(
        ["000001"],
        decision_trade_day="2026-07-10",
        daybook_effective_day="2026-07-11",
        observed_at="2026-07-10T09:00:00+00:00",
    )
    record = _record("2026-07-10T09:30:00+00:00")
    _commit_target_poll(
        target,
        run_id="semantic-poll-1",
        finished_at="2026-07-10T10:00:00+00:00",
        records=[record],
    )
    record_bootstrap_run(
        poll_run_id="semantic-poll-1",
        source="cninfo",
        symbols=target.symbols,
        lookback_days=30,
        complete=True,
        payload={"test": True},
    )
    assert acquire_worker_lease("semantic-worker") is True
    first = current_native_readiness_state(
        target.target_id, decision_at="2026-07-10T10:05:00+00:00"
    )

    renewed = _record("2026-07-10T09:30:00+00:00")
    renewed["document"]["last_seen_at"] = "2026-07-10T10:10:00+00:00"
    _commit_target_poll(
        target,
        run_id="semantic-poll-2",
        finished_at="2026-07-10T10:10:00+00:00",
        records=[renewed],
        schema_fingerprint="schema2",
        window_start="2026-06-11",
        window_end="2026-07-11",
        item_count=7,
    )
    second = current_native_readiness_state(
        target.target_id, decision_at="2026-07-10T10:15:00+00:00"
    )

    assert first["available"] is True
    assert second["available"] is True
    assert first["source_run_id"] != second["source_run_id"]
    assert first["readiness_revision"] != second["readiness_revision"]
    assert first["freshness_token"] != second["freshness_token"]
    assert first["semantic_revision"] == second["semantic_revision"]
    assert first["binding_token"] == second["binding_token"]


def test_new_selected_fact_changes_serenity_semantic_revision(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "semantic-change"))
    monkeypatch.setenv("GP_SERENITY_MODE", "native")
    target = publish_candidate_target(
        ["000001"],
        decision_trade_day="2026-07-10",
        daybook_effective_day="2026-07-11",
        observed_at="2026-07-10T09:00:00+00:00",
    )
    first_record = _record("2026-07-10T09:30:00+00:00")
    _commit_target_poll(
        target,
        run_id="semantic-change-1",
        finished_at="2026-07-10T10:00:00+00:00",
        records=[first_record],
    )
    record_bootstrap_run(
        poll_run_id="semantic-change-1",
        source="cninfo",
        symbols=target.symbols,
        lookback_days=30,
        complete=True,
        payload={"test": True},
    )
    assert acquire_worker_lease("semantic-change-worker") is True
    first = current_native_readiness_state(
        target.target_id, decision_at="2026-07-10T10:05:00+00:00"
    )

    changed_record = _record(
        "2026-07-10T10:10:00+00:00", content_hash="b" * 64, direction=-1
    )
    _commit_target_poll(
        target,
        run_id="semantic-change-2",
        finished_at="2026-07-10T10:10:00+00:00",
        records=[changed_record],
    )
    second = current_native_readiness_state(
        target.target_id, decision_at="2026-07-10T10:15:00+00:00"
    )

    assert first["available"] is True
    assert second["available"] is True
    assert first["semantic_revision"] != second["semantic_revision"]
    assert first["binding_token"] != second["binding_token"]


def test_reactivated_target_requires_a_new_poll_but_same_active_target_does_not(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "reactivation"))
    first = publish_candidate_target(
        ["000001"],
        decision_trade_day="2026-07-10",
        daybook_effective_day="2026-07-11",
        observed_at="2026-07-10T09:00:00+00:00",
    )
    coverage = [
        {
            "symbol": "000001",
            "metadata_complete": True,
            "hydration_complete": True,
            "item_count": 0,
            "window_start": "2026-06-10",
            "window_end": "2026-07-10",
        }
    ]
    commit_poll(
        source="cninfo",
        source_kind="live",
        run={
            "run_id": "poll-before-reactivation",
            "started_at": "2026-07-10T09:10:00+00:00",
            "finished_at": "2026-07-10T09:10:00+00:00",
            "elapsed_sec": 0.1,
            "status": "success",
            "complete": True,
            "request_count": 1,
            "item_count": 0,
            "stale_after_sec": 7200,
            "target_id": first.target_id,
            "target_activation_revision": first.activation_revision,
        },
        records=[],
        cursor={},
        schema_fingerprint="schema1",
        coverage=coverage,
    )
    assert candidate_target_readiness_revision(
        first.target_id, decision_at="2026-07-10T09:30:00+00:00"
    ) is not None

    publish_candidate_target(
        ["000002"],
        decision_trade_day="2026-07-10",
        daybook_effective_day="2026-07-11",
        observed_at="2026-07-10T10:00:00+00:00",
    )
    reactivated = publish_candidate_target(
        ["000001"],
        decision_trade_day="2026-07-10",
        daybook_effective_day="2026-07-11",
        observed_at="2026-07-10T10:30:00+00:00",
    )
    assert reactivated.activation_revision != first.activation_revision
    assert candidate_target_readiness_revision(
        first.target_id, decision_at="2026-07-10T10:45:00+00:00"
    ) is None

    with pytest.raises(
        RuntimeError, match="serenity_complete_target_coverage_mismatch"
    ):
        commit_poll(
            source="cninfo",
            source_kind="live",
            run={
                "run_id": "poll-overlaps-reactivation",
                "started_at": "2026-07-10T10:20:00+00:00",
                "finished_at": "2026-07-10T10:35:00+00:00",
                "elapsed_sec": 900.0,
                "status": "success",
                "complete": True,
                "request_count": 1,
                "item_count": 0,
                "stale_after_sec": 7200,
                "target_id": first.target_id,
                "target_activation_revision": first.activation_revision,
            },
            records=[],
            cursor={},
            schema_fingerprint="schema1",
            coverage=coverage,
        )

    same_active = publish_candidate_target(
        ["000001"],
        decision_trade_day="2026-07-10",
        daybook_effective_day="2026-07-11",
        observed_at="2026-07-10T10:50:00+00:00",
    )
    assert same_active.activation_revision == reactivated.activation_revision
    assert same_active.observed_at == reactivated.observed_at

    commit_poll(
        source="cninfo",
        source_kind="live",
        run={
            "run_id": "poll-after-reactivation",
            "started_at": "2026-07-10T10:40:00+00:00",
            "finished_at": "2026-07-10T10:40:00+00:00",
            "elapsed_sec": 0.1,
            "status": "success",
            "complete": True,
            "request_count": 1,
            "item_count": 0,
            "stale_after_sec": 7200,
            "target_id": first.target_id,
            "target_activation_revision": reactivated.activation_revision,
        },
        records=[],
        cursor={},
        schema_fingerprint="schema1",
        coverage=coverage,
    )
    revision = candidate_target_readiness_revision(
        first.target_id, decision_at="2026-07-10T10:45:00+00:00"
    )
    assert revision is not None
    assert revision["source_run_id"] == "poll-after-reactivation"
    assert revision["activation_revision"] == reactivated.activation_revision


def test_complete_target_poll_requires_a_positive_finite_ttl(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "invalid-ttl"))
    target = publish_candidate_target(
        ["000001"],
        decision_trade_day="2026-07-10",
        daybook_effective_day="2026-07-11",
        observed_at="2026-07-10T09:00:00+00:00",
    )
    with pytest.raises(RuntimeError, match="serenity_complete_target_ttl_invalid"):
        commit_poll(
            source="cninfo",
            source_kind="live",
            run={
                "run_id": "zero-ttl",
                "started_at": "2026-07-10T09:10:00+00:00",
                "finished_at": "2026-07-10T09:10:00+00:00",
                "elapsed_sec": 0.1,
                "status": "success",
                "complete": True,
                "request_count": 1,
                "item_count": 0,
                "stale_after_sec": 0,
                "target_id": target.target_id,
                "target_activation_revision": target.activation_revision,
            },
            records=[],
            cursor={},
            schema_fingerprint="schema1",
            coverage=[
                {
                    "symbol": "000001",
                    "metadata_complete": True,
                    "hydration_complete": True,
                    "item_count": 0,
                }
            ],
        )


def test_partial_target_poll_is_not_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "partial-target"))
    target = publish_candidate_target(
        ["000001"],
        decision_trade_day="2026-07-10",
        daybook_effective_day="2026-07-11",
        observed_at="2026-07-10T10:00:00+00:00",
    )
    commit_poll(
        source="cninfo",
        source_kind="live",
        run={
            "run_id": "partial-target-run",
            "started_at": "2026-07-10T10:00:00+00:00",
            "finished_at": "2026-07-10T10:00:00+00:00",
            "elapsed_sec": 0.2,
            "status": "partial",
            "complete": False,
            "request_count": 1,
            "item_count": 0,
            "next_due_at": "2026-07-10T10:01:00+00:00",
            "stale_after_sec": 3600,
            "target_id": target.target_id,
            "target_activation_revision": target.activation_revision,
        },
        records=[],
        cursor=None,
        schema_fingerprint="schema1",
        coverage=[
            {
                "symbol": "000001",
                "metadata_complete": True,
                "hydration_complete": False,
                "item_count": 0,
                "window_start": "2026-06-10",
                "window_end": "2026-07-10",
                "error": "hydration_incomplete",
            }
        ],
    )

    assert candidate_target_ready(
        target.target_id, decision_at="2026-07-10T10:30:00+00:00"
    ) is False
    health = status_snapshot()
    assert health["available"] is False
    assert health["last_poll_complete"] is False


def test_latest_partial_attempt_cannot_reuse_an_older_complete_target_certificate(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "target-certificate"))
    target = publish_candidate_target(
        ["000001", "000002"],
        decision_trade_day="2026-07-10",
        daybook_effective_day="2026-07-11",
        observed_at="2026-07-10T09:00:00+00:00",
    )
    full_coverage = [
        {
            "symbol": symbol,
            "metadata_complete": True,
            "hydration_complete": True,
            "item_count": 0,
            "window_start": "2026-06-10",
            "window_end": "2026-07-10",
        }
        for symbol in target.symbols
    ]
    commit_poll(
        source="cninfo",
        source_kind="live",
        run={
            "run_id": "target-full",
            "started_at": "2026-07-10T09:00:00+00:00",
            "finished_at": "2026-07-10T09:00:00+00:00",
            "elapsed_sec": 0.2,
            "status": "success",
            "complete": True,
            "request_count": 2,
            "item_count": 0,
            "next_due_at": "2026-07-10T10:00:00+00:00",
            "stale_after_sec": 3600,
            "target_id": target.target_id,
            "target_activation_revision": target.activation_revision,
        },
        records=[],
        cursor={},
        schema_fingerprint="schema1",
        coverage=full_coverage,
    )
    record_bootstrap_run(
        poll_run_id="target-full",
        source="cninfo",
        symbols=target.symbols,
        lookback_days=30,
        complete=True,
        payload={"test": True},
    )
    first_revision = candidate_target_readiness_revision(
        target.target_id, decision_at="2026-07-10T09:30:00+00:00"
    )
    assert first_revision is not None
    assert first_revision["source_run_id"] == "target-full"
    commit_poll(
        source="cninfo",
        source_kind="live",
        run={
            "run_id": "target-partial-latest",
            "started_at": "2026-07-10T10:00:00+00:00",
            "finished_at": "2026-07-10T10:00:00+00:00",
            "elapsed_sec": 0.2,
            "status": "partial",
            "complete": False,
            "request_count": 2,
            "item_count": 0,
            "next_due_at": "2026-07-10T10:01:00+00:00",
            "stale_after_sec": 3600,
            "target_id": target.target_id,
            "target_activation_revision": target.activation_revision,
        },
        records=[],
        cursor=None,
        schema_fingerprint="schema1",
        coverage=full_coverage,
    )

    signals = load_frozen_signals(
        target.symbols,
        decision_at="2026-07-10T10:30:00+00:00",
        target_id=target.target_id,
    )

    assert {signal.status for signal in signals.values()} == {"not_ready"}
    assert {signal.source_run_id for signal in signals.values()} == {None}
    assert (
        candidate_target_readiness_revision(
            target.target_id, decision_at="2026-07-10T10:30:00+00:00"
        )
        is None
    )
    assert candidate_target_ready(
        target.target_id, decision_at="2026-07-10T10:30:00+00:00"
    ) is False


def test_claimed_complete_target_poll_requires_exact_complete_symbol_coverage(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "target-commit"))
    target = publish_candidate_target(
        ["000001", "000002"],
        decision_trade_day="2026-07-10",
        daybook_effective_day="2026-07-11",
        observed_at="2026-07-10T09:00:00+00:00",
    )

    with pytest.raises(RuntimeError, match="serenity_complete_target_coverage_mismatch"):
        commit_poll(
            source="cninfo",
            source_kind="live",
            run={
                "run_id": "invalid-complete-target",
                "started_at": "2026-07-10T10:00:00+00:00",
                "finished_at": "2026-07-10T10:00:00+00:00",
                "elapsed_sec": 0.2,
                "status": "success",
                "complete": True,
                "request_count": 1,
                "item_count": 0,
                "next_due_at": "2026-07-10T11:00:00+00:00",
                "stale_after_sec": 3600,
                "target_id": target.target_id,
                "target_activation_revision": target.activation_revision,
            },
            records=[],
            cursor={},
            schema_fingerprint="schema1",
            coverage=[
                {
                    "symbol": "000001",
                    "metadata_complete": True,
                    "hydration_complete": True,
                    "item_count": 0,
                }
            ],
        )


def test_native_formula_cutover_retires_legacy_pending_once(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "formula-cutover"))
    initialize_store()
    saved = save_policy_state(
        SerenityPolicyState(
            epoch=3,
            state="suspended",
            applied_weight=0.04,
            previous_weight=0.03,
            bootstrap_run_id="serboot_existing",
            matured_days=9,
            available_results=40,
            suspension_reasons=["three_consecutive_source_or_parse_failures"],
            state_since="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-01T00:00:00+00:00",
        )
    )
    pending_id = enqueue_pending_evaluation(
        reference_snapshot_id="serref_legacy",
        decision_context_snapshot_id="dcs_legacy",
        decision_day="2026-07-01",
        epoch=saved.epoch,
        formula_version="SerenityAddon.v1",
        input_hash="legacy-input",
    )

    result = ensure_native_formula_epoch()
    state = load_policy_state()
    repeated = ensure_native_formula_epoch()
    conn = sqlite3.connect(evidence_db_path())
    try:
        pending_status = conn.execute(
            "SELECT status FROM pending_evaluations WHERE pending_id=?", (pending_id,)
        ).fetchone()[0]
        ledger_count = conn.execute(
            "SELECT COUNT(*) FROM policy_update_ledger WHERE evaluation_id='native_formula_cutover_v1'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert result["changed"] is True
    assert result["epoch"] == 4
    assert state.epoch == 4
    assert state.state == "suspended"
    assert state.applied_weight == 0.0
    assert state.previous_weight == 0.0
    assert state.matured_days == 0
    assert state.available_results == 0
    assert state.bootstrap_run_id == "serboot_existing"
    assert pending_status == "retired_formula"
    assert list_pending_evaluations() == []
    assert repeated["changed"] is False
    assert ledger_count == 1


def test_native_evaluation_does_not_trigger_formula_cutover(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "native-evaluation"))
    initialize_store()
    save_evaluation(
        {
            "evaluation_id": "sereval_native",
            "decision_day": "2026-07-01",
            "matured_at": "2026-07-08",
            "epoch": 1,
            "formula_version": "SerenityEvaluation.v1",
            "addon_formula_version": NATIVE_SERENITY_FORMULA_VERSION,
            "input_hash": "native-input",
            "learning_sample_id": "native-sample",
            "created_at": "2026-07-09T00:00:00+00:00",
        }
    )

    result = ensure_native_formula_epoch()

    assert result == {"changed": False, "reason": "no_legacy_formula_state"}


def test_expired_fact_is_reference_only_and_cannot_adjust_score(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    record = _record("2026-07-10T10:00:00+00:00")
    record["facts"][0] = record["facts"][0].model_copy(update={"published_at": "2026-01-01T00:00:00+08:00"})
    _commit(record, "run1")
    signal = load_frozen_signals(["000001"], decision_at="2026-07-10T10:30:00+00:00")["000001"]
    assert signal.availability == 0
    assert signal.status == "no_relevant_evidence"
    assert any(item.startswith("expired_evidence_excluded:") for item in signal.limitations)


def test_symbol_without_latest_poll_coverage_is_not_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    record = _record("2026-07-10T10:00:00+00:00")
    commit_poll(
        source="cninfo",
        source_kind="bootstrap",
        run={
            "run_id": "coverage-other",
            "started_at": "2026-07-10T10:00:00+00:00",
            "finished_at": "2026-07-10T10:00:00+00:00",
            "elapsed_sec": 1,
            "status": "success",
            "complete": True,
            "request_count": 1,
            "item_count": 1,
            "next_due_at": "2026-07-10T11:00:00+00:00",
            "stale_after_sec": 3600,
        },
        records=[record],
        cursor={"target_symbols": ["000002"]},
        schema_fingerprint="schema",
        coverage=[
            {
                "symbol": "000002",
                "metadata_complete": True,
                "hydration_complete": True,
                "item_count": 0,
                "window_start": "2026-06-10",
                "window_end": "2026-07-10",
            }
        ],
    )
    record_bootstrap_run(
        poll_run_id="coverage-other",
        source="cninfo",
        symbols=["000002"],
        lookback_days=30,
        complete=True,
        payload={},
    )
    signal = load_frozen_signals(["000001"], decision_at="2026-07-10T10:30:00+00:00")["000001"]
    assert signal.status == "not_ready"
    assert signal.availability == 0


def test_later_bootstrap_cannot_retroactively_ready_an_earlier_decision(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "bootstrap-asof"))
    record = _record("2026-07-10T10:00:00+00:00")
    commit_poll(
        source="cninfo",
        source_kind="live",
        run={
            "run_id": "live-before-bootstrap",
            "started_at": "2026-07-10T10:00:00+00:00",
            "finished_at": "2026-07-10T10:00:00+00:00",
            "elapsed_sec": 0.2,
            "status": "success",
            "complete": True,
            "request_count": 1,
            "item_count": 1,
            "next_due_at": "2026-07-10T11:00:00+00:00",
            "stale_after_sec": 1_000_000_000,
        },
        records=[record],
        cursor={},
        schema_fingerprint="schema1",
        coverage=[
            {
                "symbol": "000001",
                "metadata_complete": True,
                "hydration_complete": True,
                "item_count": 1,
                "window_start": "2026-06-10",
                "window_end": "2026-07-10",
            }
        ],
    )
    before = load_frozen_signals(
        ["000001"], decision_at="2026-07-10T12:00:00+00:00"
    )["000001"]
    record_bootstrap_run(
        poll_run_id="bootstrap-later",
        source="cninfo",
        symbols=["000001"],
        lookback_days=30,
        complete=True,
        payload={"test": True},
    )
    historical = load_frozen_signals(
        ["000001"], decision_at="2026-07-10T12:00:00+00:00"
    )["000001"]
    after_bootstrap = load_frozen_signals(
        ["000001"], decision_at="2026-07-15T12:00:00+00:00"
    )["000001"]

    assert before.status == "not_ready"
    assert historical.status == "not_ready"
    assert after_bootstrap.status == "available"


def test_periodic_content_revalidation_detects_same_id_new_pdf_version(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.extract_pdf_text",
        lambda data: ("证券代码000001，预计净利润同比增长35%。", "parsed"),
    )

    class Client:
        def __init__(self):
            self.payloads = [b"%PDF-first", b"%PDF-second"]

        def download_pdf(self, url, *, max_bytes):
            return self.payloads.pop(0)

    class Verifier:
        def verify(self, record, *, start, end):
            return True

    metadata = {
        "source_record_id": "same-id",
        "symbol": "000001",
        "title": "2026年半年度业绩预告",
        "source_url": "https://static.cninfo.com.cn/same.pdf",
        "published_at": "2026-07-10T00:00:00+08:00",
        "raw_metadata": {"announcementId": "same-id"},
    }
    client = Client()
    first = _record_payload(
        metadata=metadata,
        first_seen_at="2026-07-10T10:00:00+00:00",
        backfill_only=False,
        client=client,
        verifier=Verifier(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 10),
        pdf_max_bytes=1024,
        content_revalidate_hours=-1,
    )
    _commit(first, "version-run-1")
    second = _record_payload(
        metadata=metadata,
        first_seen_at="2026-07-10T11:00:00+00:00",
        backfill_only=False,
        client=client,
        verifier=Verifier(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 10),
        pdf_max_bytes=1024,
        content_revalidate_hours=-1,
    )
    assert second["version"]["version_id"] != first["version"]["version_id"]
    assert second["version"]["supersedes_version_id"] == first["version"]["version_id"]
    _commit(second, "version-run-2")
    conn = sqlite3.connect(evidence_db_path())
    try:
        assert conn.execute("SELECT COUNT(*) FROM document_versions WHERE document_id=?", (first["document"]["document_id"],)).fetchone()[0] == 2
    finally:
        conn.close()


def test_failed_content_revalidation_preserves_current_version(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "revalidation-failure"))
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.extract_pdf_text",
        lambda data: ("证券代码000001，预计净利润同比增长35%。", "parsed"),
    )

    class InitialClient:
        def download_pdf(self, url, *, max_bytes):
            return b"%PDF-original"

    class FailingClient:
        def download_pdf(self, url, *, max_bytes):
            raise RuntimeError("temporary_download_failure")

    class Verifier:
        def verify(self, record, *, start, end):
            return True

    metadata = {
        "source_record_id": "revalidation-id",
        "symbol": "000001",
        "title": "2026年半年度业绩预告",
        "source_url": "https://static.cninfo.com.cn/revalidation.pdf",
        "published_at": "2026-07-10T00:00:00+08:00",
        "raw_metadata": {"announcementId": "revalidation-id"},
    }
    first = _record_payload(
        metadata=metadata,
        first_seen_at="2026-07-10T10:00:00+00:00",
        backfill_only=False,
        client=InitialClient(),
        verifier=Verifier(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 10),
        pdf_max_bytes=1024,
        content_revalidate_hours=-1,
    )
    _commit(first, "revalidation-success")
    before = lookup_document("cninfo", "revalidation-id")

    failed = _record_payload(
        metadata=metadata,
        first_seen_at="2026-07-10T11:00:00+00:00",
        backfill_only=False,
        client=FailingClient(),
        verifier=Verifier(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 10),
        pdf_max_bytes=1024,
        content_revalidate_hours=-1,
    )
    assert failed["hydration_status"].startswith("parse_error:")
    assert failed["version"] == {}
    _commit(failed, "revalidation-failed")

    after = lookup_document("cninfo", "revalidation-id")
    assert after["current_version_id"] == before["current_version_id"]
    assert after["content_hash"] == before["content_hash"]
    assert after["raw_path"] == before["raw_path"]


def test_transient_parse_failure_does_not_poison_same_hash_retry(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "parse-retry"))
    statuses = iter(
        [
            ("", "parse_timeout"),
            ("证券代码000001，预计净利润同比增长35%。", "parsed"),
        ]
    )
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.extract_pdf_text",
        lambda data: next(statuses),
    )

    class Client:
        def download_pdf(self, url, *, max_bytes):
            return b"%PDF-identical-content"

    class Verifier:
        def verify(self, record, *, start, end):
            return True

    metadata = {
        "source_record_id": "parse-retry-id",
        "symbol": "000001",
        "title": "2026年半年度业绩预告",
        "source_url": "https://static.cninfo.com.cn/parse-retry.pdf",
        "published_at": "2026-07-10T00:00:00+08:00",
        "raw_metadata": {"announcementId": "parse-retry-id"},
    }
    first = _record_payload(
        metadata=metadata,
        first_seen_at="2026-07-10T10:00:00+00:00",
        backfill_only=False,
        client=Client(),
        verifier=Verifier(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 10),
        pdf_max_bytes=1024,
        content_revalidate_hours=-1,
    )
    assert first["version"] == {}
    _commit(first, "parse-timeout")
    assert lookup_document("cninfo", "parse-retry-id")["current_version_id"] is None

    second = _record_payload(
        metadata=metadata,
        first_seen_at="2026-07-10T11:00:00+00:00",
        backfill_only=False,
        client=Client(),
        verifier=Verifier(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 10),
        pdf_max_bytes=1024,
        content_revalidate_hours=-1,
    )
    assert second["hydration_status"] == "parsed"
    _commit(second, "parse-success")
    stored = lookup_document("cninfo", "parse-retry-id")
    assert stored["extraction_status"] == "parsed"
    assert stored["content_hash"] == second["version"]["content_hash"]


def test_evaluation_pending_and_policy_ledger_are_atomic_and_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    pending_id = enqueue_pending_evaluation(
        reference_snapshot_id="sersnap_atomic",
        decision_context_snapshot_id="dcs_atomic",
        decision_day="2026-01-02",
        epoch=1,
        formula_version=NATIVE_SERENITY_FORMULA_VERSION,
        input_hash="hash",
    )
    payload = {
        "evaluation_id": "sereval_atomic",
        "decision_day": "2026-01-02",
        "matured_at": "2026-01-09",
        "epoch": 1,
        "formula_version": "SerenityEvaluation.v1",
        "input_hash": "hash",
        "created_at": "2026-01-12T00:00:00+00:00",
    }
    assert commit_evaluation_result(payload=payload, pending_id=pending_id) == ("sereval_atomic", True)
    assert commit_evaluation_result(payload=payload, pending_id=pending_id) == ("sereval_atomic", False)
    assert list_pending_evaluations() == []

    state = SerenityPolicyState(
        state="shadow",
        bootstrap_run_id="serboot_atomic",
        state_since="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    saved = save_policy_state_with_ledger(
        state,
        expected_version=state.version,
        evaluation_id="sereval_atomic",
        ledger_payload={"from": "shadow", "to": "shadow"},
    )
    conn = sqlite3.connect(evidence_db_path())
    try:
        assert saved.version == 2
        assert conn.execute("SELECT COUNT(*) FROM policy_update_ledger").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0] == 1
    finally:
        conn.close()


def test_unresolved_correction_neutralizes_older_directional_fact(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    _commit(_record("2026-07-09T10:00:00+00:00"), "positive-run")
    correction = _record("2026-07-10T10:00:00+00:00", content_hash="c" * 64, direction=0)
    correction["document"].update(
        {
            "document_id": "serdoc_correction",
            "source_record_id": "1225000001",
            "title": "业绩预告更正公告",
            "published_at": "2026-07-10T00:00:00+08:00",
        }
    )
    correction["version"].update(
        {"version_id": "server_correction", "supersedes_version_id": None}
    )
    correction_fact = correction["facts"][0].model_copy(
        update={
            "fact_id": "serfact_correction",
            "fact_type": "reference_only",
            "published_at": "2026-07-10T00:00:00+08:00",
            "source_document_id": "serdoc_correction",
            "source_version_id": "server_correction",
            "direction": 0,
            "numeric_values": {
                "relation_type": "correction",
                "relation_status": "unresolved",
                "relation_fact_types": ["earnings_guidance"],
                "relation_target_fact_ids": ["serfact_aaaaaaaa"],
            },
        }
    )
    correction["facts"] = [correction_fact]
    correction["hypotheses"] = [
        correction["hypotheses"][0].model_copy(
            update={
                "hypothesis_id": "serhyp_correction",
                "fact_id": correction_fact.fact_id,
                "direction": 0,
                "evidence_refs": [correction_fact.fact_id],
            }
        )
    ]
    _commit(correction, "correction-run")
    signal = load_frozen_signals(["000001"], decision_at="2026-07-10T10:30:00+00:00")["000001"]
    assert signal.availability == 0
    assert signal.direction == 0
    assert "unresolved_correction_relation_no_ranking_effect" in signal.limitations


def test_future_or_malformed_fact_timestamps_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "future"))
    future = _record("2026-07-12T10:00:00+00:00")
    future["facts"][0] = future["facts"][0].model_copy(
        update={"published_at": "2026-07-12T00:00:00+08:00"}
    )
    _commit(future, "future-run")
    signal = load_frozen_signals(["000001"], decision_at="2026-07-10T10:30:00+00:00")["000001"]
    assert signal.availability == 0
    assert signal.fact_ids == []
    assert not any("serfact_" in item for item in signal.limitations)

    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "malformed"))
    malformed = _record("not-a-time")
    _commit(malformed, "malformed-run")
    signal = load_frozen_signals(["000001"], decision_at="2026-07-10T10:30:00+00:00")["000001"]
    assert signal.availability == 0
    assert signal.fact_ids == []
    assert not any("serfact_" in item for item in signal.limitations)


def test_legacy_fractional_quality_verified_fact_is_quarantined(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "legacy"))
    record = _record("2026-07-10T10:00:00+00:00")
    record["facts"][0] = record["facts"][0].model_copy(update={"source_quality": 0.9})
    _commit(record, "legacy-run")
    signal = load_frozen_signals(
        ["000001"], decision_at="2026-07-10T10:30:00+00:00"
    )["000001"]
    assert signal.availability == 0
    assert any(
        item.startswith("legacy_unverified_fact_quarantined:")
        for item in signal.limitations
    )


def test_unverified_correction_freezes_older_verified_direction(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "unverified-correction"))
    _commit(_record("2026-07-09T10:00:00+00:00"), "verified-positive")
    correction = _record(
        "2026-07-10T10:00:00+00:00",
        content_hash="d" * 64,
        direction=0,
    )
    correction["document"].update(
        {
            "document_id": "serdoc_unverified_correction",
            "source_record_id": "1225000002",
            "title": "业绩预告更正公告",
            "published_at": "2026-07-10T00:00:00+08:00",
        }
    )
    correction["version"].update(
        {"version_id": "server_unverified_correction", "supersedes_version_id": None}
    )
    correction_fact = correction["facts"][0].model_copy(
        update={
            "fact_id": "serfact_unverified_correction",
            "fact_type": "reference_only",
            "published_at": "2026-07-10T00:00:00+08:00",
            "source_document_id": "serdoc_unverified_correction",
            "source_version_id": "server_unverified_correction",
            "direction": 0,
            "source_quality": 0.0,
            "verification_state": "unverified",
            "numeric_values": {
                "relation_type": "correction",
                "relation_status": "unresolved",
                "relation_fact_types": ["earnings_guidance"],
                "relation_target_fact_ids": ["serfact_aaaaaaaa"],
            },
        }
    )
    correction["facts"] = [correction_fact]
    correction["hypotheses"] = [
        correction["hypotheses"][0].model_copy(
            update={
                "hypothesis_id": "serhyp_unverified_correction",
                "fact_id": correction_fact.fact_id,
                "direction": 0,
                "source_quality": 0.0,
                "status": "unverified",
                "evidence_refs": [correction_fact.fact_id],
            }
        )
    ]
    _commit(correction, "unverified-correction-run")
    signal = load_frozen_signals(
        ["000001"], decision_at="2026-07-10T10:30:00+00:00"
    )["000001"]
    assert signal.availability == 0
    assert signal.direction == 0
    assert any(
        item.startswith("unverified_correction_freezes_prior_evidence:")
        for item in signal.limitations
    )


def test_unscoped_live_correction_zeros_only_serenity_contribution(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "unscoped-correction"))
    _commit(_record("2026-07-09T10:00:00+00:00"), "verified-positive")
    correction = _record(
        "2026-07-10T10:00:00+00:00",
        content_hash="9" * 64,
        direction=0,
    )
    correction["document"].update(
        {
            "document_id": "serdoc_unscoped_correction",
            "source_record_id": "unscoped-correction",
            "title": "更正公告",
            "published_at": "2026-07-10T00:00:00+08:00",
        }
    )
    correction["version"].update(
        {"version_id": "server_unscoped_correction", "supersedes_version_id": None}
    )
    correction["facts"][0] = correction["facts"][0].model_copy(
        update={
            "fact_id": "serfact_unscoped_correction",
            "fact_type": "reference_only",
            "published_at": "2026-07-10T00:00:00+08:00",
            "source_document_id": "serdoc_unscoped_correction",
            "source_version_id": "server_unscoped_correction",
            "direction": 0,
            "numeric_values": {
                "relation_type": "correction",
                "relation_status": "unresolved",
                "relation_fact_types": [],
                "relation_target_keys": [],
            },
        }
    )
    correction["hypotheses"] = []
    _commit(correction, "unscoped-correction-run")

    signal = load_frozen_signals(
        ["000001"], decision_at="2026-07-10T10:30:00+00:00"
    )["000001"]

    assert signal.status == "source_error"
    assert signal.availability == 0
    assert signal.learning_eligible is False
    assert signal.direction == 0
    assert any(
        item.startswith("unresolved_relation_target_unknown_no_ranking_effect:")
        for item in signal.limitations
    )


def test_backfill_correction_cannot_freeze_live_fact(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "backfill-correction"))
    _commit(_record("2026-07-09T10:00:00+00:00"), "verified-positive")
    correction = _record(
        "2026-07-10T10:00:00+00:00",
        content_hash="e" * 64,
        direction=0,
    )
    correction["document"].update(
        {
            "document_id": "serdoc_backfill_correction",
            "source_record_id": "1225000003",
            "title": "业绩预告更正公告",
            "published_at": "2026-07-10T00:00:00+08:00",
            "backfill_only": True,
        }
    )
    correction["version"].update(
        {"version_id": "server_backfill_correction", "supersedes_version_id": None}
    )
    correction_fact = correction["facts"][0].model_copy(
        update={
            "fact_id": "serfact_backfill_correction",
            "fact_type": "reference_only",
            "published_at": "2026-07-10T00:00:00+08:00",
            "source_document_id": "serdoc_backfill_correction",
            "source_version_id": "server_backfill_correction",
            "direction": 0,
            "backfill_only": True,
            "numeric_values": {
                "relation_type": "correction",
                "relation_status": "unresolved",
                "relation_fact_types": ["earnings_guidance"],
                "relation_target_fact_ids": ["serfact_aaaaaaaa"],
            },
        }
    )
    correction["facts"] = [correction_fact]
    correction["hypotheses"] = []
    _commit(correction, "backfill-correction-run")

    signal = load_frozen_signals(
        ["000001"], decision_at="2026-07-10T10:30:00+00:00"
    )["000001"]

    assert signal.availability == 1
    assert signal.direction == 1
    assert "serfact_backfill_correction" in signal.fact_ids
    assert "unresolved_correction_relation_no_ranking_effect" not in signal.limitations


def test_backfill_reference_facts_cannot_crowd_out_live_direction(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "backfill-crowding"))
    _commit(_record("2026-07-09T10:00:00+00:00"), "verified-live")
    for index, marker in enumerate(("f", "a", "b"), start=1):
        record = _record(
            f"2026-07-10T1{index}:00:00+00:00",
            content_hash=marker * 64,
            direction=0,
        )
        document_id = f"serdoc_backfill_neutral_{index}"
        version_id = f"server_backfill_neutral_{index}"
        record["document"].update(
            {
                "document_id": document_id,
                "source_record_id": f"backfill-neutral-{index}",
                "title": "股份回购进展公告",
                "published_at": f"2026-07-10T0{index}:00:00+08:00",
                "backfill_only": True,
            }
        )
        record["version"].update(
            {"version_id": version_id, "supersedes_version_id": None}
        )
        record["facts"][0] = record["facts"][0].model_copy(
            update={
                "fact_id": f"serfact_backfill_neutral_{index}",
                "fact_type": "reference_only",
                "published_at": f"2026-07-10T0{index}:00:00+08:00",
                "source_document_id": document_id,
                "source_version_id": version_id,
                "direction": 0,
                "backfill_only": True,
            }
        )
        record["hypotheses"] = []
        _commit(record, f"backfill-neutral-run-{index}")

    signal = load_frozen_signals(
        ["000001"], decision_at="2026-07-10T13:30:00+00:00"
    )["000001"]

    assert signal.learning_eligible is True
    assert signal.availability == 1
    assert signal.direction == 1
    assert "serfact_aaaaaaaa" in signal.fact_ids


def test_learning_sample_is_idempotent_and_deduped_before_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "evaluation-dedupe"))
    base = {
        "decision_day": "2026-01-02",
        "matured_at": "2026-01-09",
        "epoch": 1,
        "formula_version": "SerenityEvaluation.v1",
        "input_hash": "hash",
        "learning_sample_id": "sersample_same",
        "created_at": "2026-01-12T00:00:00+00:00",
    }
    assert save_evaluation({**base, "evaluation_id": "sereval_first"}) == (
        "sereval_first",
        True,
    )
    assert save_evaluation({**base, "evaluation_id": "sereval_repeat"}) == (
        "sereval_first",
        False,
    )
    assert save_evaluation(
        {
            **base,
            "evaluation_id": "sereval_unique",
            "decision_day": "2025-12-31",
            "learning_sample_id": "sersample_unique",
        }
    )[1] is True

    conn = sqlite3.connect(evidence_db_path())
    try:
        for index in range(3):
            payload = {
                **base,
                "evaluation_id": f"sereval_legacy_{index}",
                "decision_day": f"2026-01-0{3 + index}",
            }
            conn.execute(
                """
                INSERT INTO evaluations(
                    evaluation_id,decision_day,matured_at,epoch,formula_version,input_hash,
                    learning_sample_id,payload_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    payload["evaluation_id"],
                    payload["decision_day"],
                    payload["matured_at"],
                    payload["epoch"],
                    payload["formula_version"],
                    payload["input_hash"],
                    payload["learning_sample_id"],
                    json.dumps(payload),
                    payload["created_at"],
                ),
            )
        conn.commit()
    finally:
        conn.close()

    evaluations = list_evaluations(epoch=1, limit=2)
    assert len(evaluations) == 2
    assert {item["learning_sample_id"] for item in evaluations} == {
        "sersample_same",
        "sersample_unique",
    }


def test_metadata_revisions_are_append_only(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "metadata"))
    first = _record("2026-07-10T10:00:00+00:00")
    _commit(first, "metadata-1")
    revised = _record("2026-07-10T11:00:00+00:00")
    revised["document"]["title"] = "业绩预告（修订标题）"
    revised["document"]["raw_metadata"] = {"announcementId": "1225000000", "revision": 2}
    _commit(revised, "metadata-2")
    conn = sqlite3.connect(evidence_db_path())
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM document_metadata_versions WHERE document_id='serdoc_test'"
        ).fetchone()[0] == 2
    finally:
        conn.close()


def test_bootstrap_document_cannot_be_relabelled_live_on_revalidation(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "backfill-revalidation"))
    original = _record("2026-07-10T10:00:00+00:00")
    original["document"]["backfill_only"] = True
    original["facts"][0] = original["facts"][0].model_copy(update={"backfill_only": True})
    _commit(original, "bootstrap-origin")
    monkeypatch.setattr(
        "gp_assistant.serenity.worker.extract_pdf_text",
        lambda data: ("证券代码000001。2026年半年度业绩预告。净利润同比增长35%。", "parsed"),
    )

    class Client:
        def download_pdf(self, url, *, max_bytes):
            return b"%PDF-live-revalidation"

    class Verifier:
        def verify(self, record, *, start, end):
            return True

    payload = _record_payload(
        metadata={
            "source_record_id": "1225000000",
            "symbol": "000001",
            "title": "2026年半年度业绩预告",
            "source_url": "https://static.cninfo.com.cn/live.pdf",
            "published_at": "2026-07-10T00:00:00+08:00",
            "raw_metadata": {"announcementId": "1225000000"},
        },
        first_seen_at="2026-07-11T10:00:00+00:00",
        backfill_only=False,
        client=Client(),
        verifier=Verifier(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 11),
        pdf_max_bytes=1024,
        content_revalidate_hours=-1,
    )
    assert payload["document"]["backfill_only"] is True
    assert payload["facts"]
    assert all(fact.backfill_only for fact in payload["facts"])


def test_reference_and_pending_are_persisted_in_one_transaction(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "reference-atomic"))
    signal = FrozenSerenitySignal(
        symbol="000001",
        status="no_relevant_evidence",
        decision_at="2026-01-02T15:00:00+08:00",
        generated_at="2026-01-02T15:00:00+08:00",
        input_hash="none",
    )
    adaptive = {
        "serenity_policy": {
            "state": "shadow",
            "applied_weight": 0.0,
            "baseline_selected_symbols": [],
            "applied_selected_symbols": [],
        },
        "serenity_counterfactuals": [],
        "serenity_reference_counterfactuals": [],
    }
    snapshot = build_reference_snapshot(
        decision_context_snapshot_id="dcs_atomic_reference",
        decision_day="2026-01-02",
        decision_at="2026-01-02T15:00:00+08:00",
        adaptive_output=adaptive,
        signals={"000001": signal},
    )
    snapshot_id, pending_id = save_reference_and_enqueue_pending(
        snapshot,
        decision_day="2026-01-02",
        epoch=1,
        formula_version=NATIVE_SERENITY_FORMULA_VERSION,
    )
    assert snapshot_id == snapshot.snapshot_id
    assert pending_id
    assert [row["reference_snapshot_id"] for row in list_pending_evaluations()] == [snapshot_id]


def test_pending_identity_conflict_rolls_back_instead_of_silently_reusing(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "pending-conflict"))
    signal = FrozenSerenitySignal(
        symbol="000001",
        status="no_relevant_evidence",
        decision_at="2026-01-02T15:00:00+08:00",
        generated_at="2026-01-02T15:00:00+08:00",
        input_hash="none",
    )
    snapshot = build_reference_snapshot(
        decision_context_snapshot_id="dcs_pending_conflict",
        decision_day="2026-01-02",
        decision_at="2026-01-02T15:00:00+08:00",
        adaptive_output={
            "serenity_policy": {"state": "shadow", "applied_weight": 0.0},
            "serenity_counterfactuals": [],
            "serenity_reference_counterfactuals": [],
        },
        signals={"000001": signal},
    )
    _, pending_id = save_reference_and_enqueue_pending(
        snapshot,
        decision_day="2026-01-02",
        epoch=1,
        formula_version=NATIVE_SERENITY_FORMULA_VERSION,
    )
    with sqlite3.connect(evidence_db_path()) as conn:
        conn.execute(
            "UPDATE pending_evaluations SET decision_day=? WHERE pending_id=?",
            ("2026-01-03", pending_id),
        )
        conn.commit()

    with pytest.raises(
        RuntimeError, match="serenity_pending_evaluation_immutable_conflict"
    ):
        save_reference_and_enqueue_pending(
            snapshot,
            decision_day="2026-01-02",
            epoch=1,
            formula_version=NATIVE_SERENITY_FORMULA_VERSION,
        )


def test_commit_rechecks_worker_lease_in_same_write_transaction(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "lease"))
    assert acquire_worker_lease("right-owner") is True
    with pytest.raises(RuntimeError, match="lease_lost_before_commit"):
        commit_poll(
            source="cninfo",
            source_kind="live",
            run={
                "run_id": "lease-run",
                "started_at": "2026-07-10T10:00:00+00:00",
                "finished_at": "2026-07-10T10:00:01+00:00",
                "elapsed_sec": 1,
                "status": "success",
                "complete": True,
                "request_count": 1,
                "item_count": 0,
                "next_due_at": "2026-07-10T11:00:00+00:00",
                "stale_after_sec": 3600,
            },
            records=[],
            cursor={},
            schema_fingerprint="schema",
            lease_owner_id="wrong-owner",
        )


def test_off_mode_health_reports_effective_zero_weight(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "off-mode"))
    cfg = SerenityConfig(mode="off")
    monkeypatch.setattr(
        "gp_assistant.serenity.store.load_config",
        lambda: SimpleNamespace(serenity=cfg),
    )
    state = SerenityPolicyState(
        state="active",
        applied_weight=0.08,
        bootstrap_run_id="serboot_stored",
        state_since="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    save_policy_state(state)
    status = status_snapshot()
    assert status["mode"] == "off"
    assert status["policy_state"] == "active"
    assert status["stored_applied_weight"] == 0.08
    assert status["applied_weight"] == 0.0
