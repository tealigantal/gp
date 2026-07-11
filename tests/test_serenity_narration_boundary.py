import pytest

from gp_assistant.contracts.objects import AdvicePick, AdviceRun, BoardEntry, Judgment, ReplyBundle
from gp_assistant.decision_engine.serenity_policy import build_reference_snapshot
from gp_assistant.runtime.context_engine import _serenity_detail
from gp_assistant.runtime.grounding import validate_reply
from gp_assistant.serenity.models import FrozenSerenitySignal, SerenityFact
from gp_assistant.serenity.store import save_reference_snapshot


def test_narration_loads_only_compact_target_fact(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    fact = SerenityFact(
        fact_id="serfact_target",
        symbol="000001",
        fact_type="earnings_guidance",
        claim="公司披露了可量化的业绩方向变化。",
        published_at="2026-07-10T00:00:00+08:00",
        effective_available_at="2026-07-10T10:00:00+08:00",
        source_document_id="serdoc_target",
        source_version_id="server_target",
        source="cninfo",
        source_url="https://static.cninfo.com.cn/target.pdf",
        content_sha256="a" * 64,
        direction=1,
        confidence=0.9,
        source_quality=1.0,
        verification_state="verified",
        evidence_excerpt="净利润同比增长 35% 至 50%。" + "X" * 500,
    )
    signal = FrozenSerenitySignal(
        symbol="000001",
        status="available",
        availability=1,
        learning_eligible=False,
        direction=1,
        confidence=0.9,
        source_quality=1.0,
        decision_at="2026-07-10T15:00:00+08:00",
        generated_at="2026-07-10T15:00:00+08:00",
        fact_ids=[fact.fact_id],
        facts=[fact],
        input_hash="input",
    )
    adaptive = {
        "serenity_policy": {"state": "shadow", "applied_weight": 0.0, "baseline_selected_symbols": ["000001"], "applied_selected_symbols": ["000001"]},
        "serenity_counterfactuals": [],
    }
    snapshot = build_reference_snapshot(
        decision_context_snapshot_id="dcs_target",
        decision_day="2026-07-10",
        decision_at=signal.decision_at,
        adaptive_output=adaptive,
        signals={"000001": signal},
    )
    save_reference_snapshot(snapshot)
    detail = _serenity_detail(
        {"serenity": {"reference_snapshot_id": snapshot.snapshot_id}},
        {"serenity_reference": {}, "serenity_policy": {"state": "shadow", "applied_weight": 0.0}},
        "000001",
    )
    assert detail["facts"][0]["fact_id"] == "serfact_target"
    assert detail["facts"][0]["backfill_only"] is False
    assert detail["binding_effect_allowed"] is False
    assert len(detail["facts"][0]["evidence_excerpt"]) <= 241
    assert "PDF" not in str(detail)

    other = _serenity_detail(
        {"serenity": {"reference_snapshot_id": snapshot.snapshot_id}},
        {"serenity_reference": {}, "serenity_policy": {"state": "shadow"}},
        "000002",
    )
    assert other["facts"] == []


def _grounding_objects(
    *,
    status="available",
    policy_state="shadow",
    weight=0.0,
    non_binding=True,
    learning_eligible=False,
    adjustment=0.0,
):
    def _entry(symbol, rank, fact_id):
        serenity = {
            "status": status,
            "policy_state": policy_state,
            "weight": weight,
            "non_binding": non_binding,
            "learning_eligible": learning_eligible,
            "adjustment": adjustment,
            "fact_ids": [fact_id],
        }
        pick = AdvicePick(
            symbol=symbol,
            rank=rank,
            explain_context={"serenity": serenity},
        )
        return BoardEntry(
            symbol=symbol,
            rank=rank,
            final_score=0.5,
            live_score=0.5,
            execution_state="watch",
            can_open=False,
            stretched=False,
            invalidated=False,
            summary="test",
            pick=pick,
            explain_context={"serenity": serenity},
        )

    first = _entry("000001", 1, "serfact_first")
    second = _entry("000002", 2, "serfact_second")
    run = AdviceRun(
        run_id="run_serenity_grounding",
        session_id="session",
        book_version="book",
        created_at="2026-07-10T15:00:00+08:00",
        trading_day="20260710",
        picks=[first, second],
    )
    return Judgment(kind="pick_detail", summary="test", run=run)


def test_grounding_rejects_shadow_rank_effect_claim():
    judgment = _grounding_objects()
    reply = ReplyBundle(
        session_id="session",
        text="Serenity 在 shadow 阶段改变了排名。",
        symbols=["000001"],
        evidence_refs=["serfact_first"],
    )
    with pytest.raises(RuntimeError, match="reference-only Serenity"):
        validate_reply(reply, judgment)


def test_grounding_rejects_stale_as_no_bad_news():
    judgment = _grounding_objects(status="stale")
    reply = ReplyBundle(
        session_id="session",
        text="公告面没有坏消息，所以可以放心。",
        symbols=["000001"],
        evidence_refs=["serfact_first"],
    )
    with pytest.raises(RuntimeError, match="missing Serenity evidence"):
        validate_reply(reply, judgment)


def test_grounding_allows_general_risk_language_when_serenity_is_not_mentioned():
    judgment = _grounding_objects(status="no_relevant_evidence")
    reply = ReplyBundle(
        session_id="session",
        text="当前没有明显的结构性风险，但仍需遵守止损。",
        symbols=["000001"],
        evidence_refs=[],
    )
    validate_reply(reply, judgment)


def test_grounding_rejects_non_target_fact_reference():
    judgment = _grounding_objects()
    reply = ReplyBundle(
        session_id="session",
        text="第一只仅作公告参考。",
        symbols=["000001"],
        evidence_refs=["serfact_second"],
    )
    with pytest.raises(RuntimeError, match="outside grounded judgment scope"):
        validate_reply(reply, judgment)


def test_grounding_does_not_borrow_binding_state_from_another_pick():
    judgment = _grounding_objects(
        policy_state="active",
        weight=0.08,
        non_binding=True,
        learning_eligible=False,
        adjustment=0.0,
    )
    second = judgment.run.picks[1].explain_context["serenity"]
    second.update(
        {
            "non_binding": False,
            "learning_eligible": True,
            "adjustment": 0.05,
        }
    )
    reply = ReplyBundle(
        session_id="session",
        text="公告催化推动第一只位次前移。",
        symbols=["000001"],
        evidence_refs=["serfact_first"],
    )
    with pytest.raises(RuntimeError, match="reference-only Serenity"):
        validate_reply(reply, judgment)


def test_grounding_rejects_mixed_multi_symbol_binding_rank_claim():
    judgment = _grounding_objects(
        policy_state="active",
        weight=0.08,
        non_binding=True,
        learning_eligible=False,
        adjustment=0.0,
    )
    second = judgment.run.picks[1].explain_context["serenity"]
    second.update(
        {
            "non_binding": False,
            "learning_eligible": True,
            "adjustment": 0.05,
        }
    )
    reply = ReplyBundle(
        session_id="session",
        text="公告催化推动候选位次前移。",
        symbols=["000001", "000002"],
        evidence_refs=["serfact_first", "serfact_second"],
    )

    with pytest.raises(RuntimeError, match="reference-only Serenity"):
        validate_reply(reply, judgment)


@pytest.mark.parametrize(
    "text",
    [
        "Serenity 调整了候选排序。",
        "Serenity 改变了推荐顺序。",
    ],
)
def test_grounding_rejects_nonbinding_selection_effect_synonyms(text):
    judgment = _grounding_objects()
    reply = ReplyBundle(
        session_id="session",
        text=text,
        symbols=["000001"],
        evidence_refs=["serfact_first"],
    )
    with pytest.raises(RuntimeError, match="reference-only Serenity"):
        validate_reply(reply, judgment)


def test_grounding_rejects_unknown_source_as_no_negative_announcement():
    judgment = _grounding_objects(status="source_error")
    reply = ReplyBundle(
        session_id="session",
        text="目前未看到负面公告。",
        symbols=["000001"],
        evidence_refs=["serfact_first"],
    )
    with pytest.raises(RuntimeError, match="missing Serenity evidence"):
        validate_reply(reply, judgment)
