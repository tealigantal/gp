from __future__ import annotations

import json
from hashlib import sha256

import pytest

from gp_assistant.agent_store import AgentStore, SnapshotIntegrityError
from gp_assistant.serenity.models import SerenityFact
from gp_assistant.runtime.native_snapshot import native_snapshot_integrity_errors
from tests.agent.test_agent_store import make_book


def _published(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    snapshot = store.publish_book(make_book())
    return store, snapshot


def _attach_fact(book, *, published_at: str, lineage_content_hash: str | None = None):
    record = book.daybook.source_meta["serenity_native_attestation"]["candidates"][
        "600519"
    ]
    fact = SerenityFact(
        fact_id="serfact_native_time",
        symbol="600519",
        fact_type="announcement",
        claim="公司发布一项中性公告。",
        published_at=published_at,
        effective_available_at=published_at,
        source_document_id="serdoc_native_time",
        source_version_id="server_native_time",
        source="cninfo",
        source_url="https://example.test/native.pdf",
        content_sha256="a" * 64,
        direction=0,
        confidence=0.9,
        source_quality=1.0,
        verification_state="verified",
    )
    lineage = dict(record["lineage"])
    lineage["facts"] = {
        fact.fact_id: {
            "document_id": fact.source_document_id,
            "version_id": fact.source_version_id,
            "content_hash": lineage_content_hash or fact.content_sha256,
            "document_first_seen_at": published_at,
            "version_first_seen_at": published_at,
        }
    }
    record["facts"] = [fact.model_dump(mode="json")]
    record["fact_ids"] = [fact.fact_id]
    record["lineage"] = lineage
    record["input_hash"] = sha256(
        json.dumps(
            {
                "symbol": "600519",
                "decision_at": record["decision_at"],
                "target_id": record["target_id"],
                "status": record["status"],
                "alpha_value": record["alpha_value"],
                "facts": record["facts"],
                "lineage": lineage,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    for pick in (book.daybook.picks[0], book.board[0].pick):
        for container in (pick.explain_context["serenity"], pick.meta["serenity"]):
            container["fact_ids"] = [fact.fact_id]
            container["lineage"] = lineage
            container["input_hash"] = record["input_hash"]
    book.board[0].explain_context["serenity"] = dict(
        book.board[0].pick.explain_context["serenity"]
    )


def test_valid_native_attestation_covers_target_math_and_projection(tmp_path):
    store, snapshot = _published(tmp_path)
    book = store.book_for_snapshot(snapshot)

    assert native_snapshot_integrity_errors(snapshot, book) == []


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda book: book.daybook.source_meta["serenity_candidate_target"].update(
                {"input_hash": "forged-target-hash"}
            ),
            "native_snapshot_target_identity_invalid",
        ),
        (
            lambda book: book.daybook.source_meta["serenity_native_attestation"][
                "candidates"
            ]["600519"].update({"effective_weight": 7.0}),
            "native_snapshot_serenity_weight_invalid:600519",
        ),
        (
            lambda book: book.daybook.source_meta["serenity_native_attestation"][
                "candidates"
            ]["600519"].update({"score_contribution": -0.77}),
            "native_snapshot_serenity_contribution_mismatch:600519",
        ),
        (
            lambda book: book.daybook.source_meta["serenity_native_attestation"][
                "candidates"
            ]["600519"].update({"lineage": {"garbage": "ok"}}),
            "native_snapshot_alpha_lineage_invalid:600519",
        ),
        (
            lambda book: book.daybook.source_meta["serenity_native_attestation"].update(
                {"candidates": {}}
            ),
            "native_snapshot_attestation_target_coverage_invalid",
        ),
        (
            lambda book: book.daybook.source_meta["serenity_native_attestation"].update(
                {"ranked_symbols": []}
            ),
            "native_snapshot_attested_ranking_invalid",
        ),
    ],
)
def test_native_attestation_rejects_forged_target_math_lineage_and_ranking(
    tmp_path, mutation, reason
):
    store, snapshot = _published(tmp_path)
    book = store.book_for_snapshot(snapshot)
    mutation(book)

    assert native_snapshot_integrity_errors(snapshot, book) == [reason]


def test_native_attestation_rejects_board_and_pick_serenity_drift(tmp_path):
    store, snapshot = _published(tmp_path)
    book = store.book_for_snapshot(snapshot)
    book.board[0].explain_context["serenity"]["source_run_id"] = "other-run"

    assert native_snapshot_integrity_errors(snapshot, book) == [
        "native_snapshot_board_serenity_mirror_invalid:600519"
    ]


def test_native_attestation_recomputes_and_rejects_forged_semantic_revision(
    tmp_path,
):
    store, snapshot = _published(tmp_path)
    book = store.book_for_snapshot(snapshot)
    forged = "f" * 64
    meta = book.daybook.source_meta
    meta["serenity_semantic_revision"] = forged
    attestation = meta["serenity_native_attestation"]
    attestation["semantic_revision"] = forged
    attestation["candidates"]["600519"]["semantic_revision"] = forged

    assert native_snapshot_integrity_errors(snapshot, book) == [
        "native_snapshot_semantic_revision_invalid"
    ]


def test_publish_rejects_a_ready_snapshot_with_forged_native_math(tmp_path):
    book = make_book()
    book.daybook.source_meta["serenity_native_attestation"]["candidates"][
        "600519"
    ]["score_contribution"] = 0.5

    with pytest.raises(
        SnapshotIntegrityError,
        match="native_snapshot_serenity_contribution_mismatch:600519",
    ):
        AgentStore(tmp_path / "agent.db").publish_book(book)


def test_complete_scored_batch_cannot_be_relabelled_as_no_trade(tmp_path):
    store, snapshot = _published(tmp_path)
    book = store.book_for_snapshot(snapshot)
    book.daybook.source_meta["decision"] = "no_trade"
    attestation = book.daybook.source_meta["serenity_native_attestation"]
    attestation["decision"] = "no_trade"
    attestation["selected_symbols"] = []
    book.daybook.picks = []
    book.board = []
    snapshot = type(
        "Snapshot",
        (),
        {
            **snapshot.__dict__,
            "decision": "no_trade",
        },
    )()

    assert native_snapshot_integrity_errors(snapshot, book) == [
        "native_snapshot_attested_topk_invalid"
    ]


def test_publish_cannot_bypass_native_validation_by_forging_policy_name(tmp_path):
    book = make_book()
    book.daybook.source_meta["selection_policy"] = "forged-policy"

    with pytest.raises(
        SnapshotIntegrityError, match="native_snapshot_policy_incompatible"
    ):
        AgentStore(tmp_path / "agent.db").publish_book(book)


def test_ready_snapshot_requires_current_producer_and_allow_gate(tmp_path):
    old = make_book()
    old.daybook.producer = {
        **old.daybook.producer,
        "revision": "old-image",
        "source_digest": "old-source",
    }
    with pytest.raises(
        SnapshotIntegrityError, match="native_snapshot_producer_incompatible"
    ):
        AgentStore(tmp_path / "old.db").publish_book(old)

    blocked = make_book()
    blocked.gate.state = "BLOCKED"
    with pytest.raises(
        SnapshotIntegrityError, match="native_snapshot_tradeable_gate_invalid"
    ):
        AgentStore(tmp_path / "blocked.db").publish_book(blocked)


def test_ready_snapshot_binds_decision_context_rank_and_board_score(tmp_path):
    missing_context = make_book()
    missing_context.daybook.source_meta.pop("decision_context_snapshot_id")
    with pytest.raises(
        SnapshotIntegrityError, match="native_snapshot_decision_context_missing"
    ):
        AgentStore(tmp_path / "missing-context.db").publish_book(missing_context)

    wrong_rank = make_book()
    wrong_rank.daybook.picks[0].rank = 7
    with pytest.raises(
        SnapshotIntegrityError, match="native_snapshot_pick_projection_invalid"
    ):
        AgentStore(tmp_path / "wrong-rank.db").publish_book(wrong_rank)

    wrong_score = make_book()
    wrong_score.board[0].final_score = 0.123
    with pytest.raises(
        SnapshotIntegrityError, match="native_snapshot_board_projection_invalid"
    ):
        AgentStore(tmp_path / "wrong-score.db").publish_book(wrong_score)


def test_native_attestation_rejects_future_facts_and_fact_lineage_mismatch(tmp_path):
    store, snapshot = _published(tmp_path)
    future = store.book_for_snapshot(snapshot)
    _attach_fact(future, published_at="2026-07-13T11:00:00+08:00")
    assert native_snapshot_integrity_errors(snapshot, future) == [
        "native_snapshot_alpha_fact_lineage_invalid:600519"
    ]

    mismatch = store.book_for_snapshot(snapshot)
    _attach_fact(
        mismatch,
        published_at="2026-07-13T09:45:00+08:00",
        lineage_content_hash="b" * 64,
    )
    assert native_snapshot_integrity_errors(snapshot, mismatch) == [
        "native_snapshot_alpha_fact_lineage_invalid:600519"
    ]


def test_scored_candidate_cannot_be_synchronously_relabelled_as_excluded(tmp_path):
    store, snapshot = _published(tmp_path)
    book = store.book_for_snapshot(snapshot)
    record = book.daybook.source_meta["serenity_native_attestation"]["candidates"][
        "600519"
    ]
    record["scored"] = False
    record["exclusion_reason"] = "candidate_hard_block"
    attestation = book.daybook.source_meta["serenity_native_attestation"]
    attestation["ranked_symbols"] = []
    attestation["selected_symbols"] = []
    attestation["decision"] = "no_trade"
    book.daybook.source_meta["decision"] = "no_trade"
    book.daybook.picks = []
    book.board = []
    relabelled = type(
        "Snapshot",
        (),
        {**snapshot.__dict__, "decision": "no_trade", "tradeable": False},
    )()

    assert native_snapshot_integrity_errors(relabelled, book) == [
        "native_snapshot_unscored_candidate_unexplained:600519"
    ]
