from __future__ import annotations

import json

import pytest

from gp_assistant.contracts.objects import (
    AdvicePick,
    AdviceRun,
    BoardEntry,
    DayBook,
    EvidencePack,
    ExitDecisionArtifact,
    Judgment,
    MarketBook,
    RunChangeArtifact,
    SessionState,
    SingleStockAnalysisArtifact,
    TranscriptEvent,
    TurnFrame,
)
from gp_assistant.core.errors import LLMPayloadBudgetExceeded
from gp_assistant.llm.client import LLMClient
from gp_assistant.llm.narrate import SYSTEM
from gp_assistant.runtime import context_engine, turn_loop
from gp_assistant.runtime.context_budget import (
    LLM_HARD_CAP_BYTES,
    ROUTING_PAYLOAD_LIMIT_BYTES,
    TOOL_EVIDENCE_PAYLOAD_LIMIT_BYTES,
    context_size_report,
    serialized_size_bytes,
)
from gp_assistant.runtime.narrator import build_reply


def _entry(symbol: str, rank: int, *, marker: str = "detail") -> BoardEntry:
    explain = {
        "adaptive_policy": {"version": "v1", "marker": marker},
        "adaptive_score": 0.81 - rank / 100,
        "calibrated_probability": 0.63 - rank / 100,
        "recommendation_strength": "strong" if rank <= 3 else "medium",
        "adaptive_action": "WATCH",
        "feature_coverage": 0.9,
        "expert_scores": {"trend": 0.8},
        "expert_contributions": {"trend": 0.3},
        "missing_features": ["northbound_flow", "news_sentiment"],
        "entry_low": 10.0 + rank,
        "entry_high": 10.2 + rank,
        "trigger_price": 10.15 + rank,
        "stop_price": 9.6 + rank,
        "take1": 10.8 + rank,
        "take2": 11.2 + rank,
        "main_risks": [f"risk-{marker}", "volume_not_confirmed"],
        "why_ranked_here": f"rank-reason-{marker}",
        "detail_marker": marker,
    }
    pick = AdvicePick(
        symbol=symbol,
        name=f"候选{rank}",
        rank=rank,
        industry="科技" if rank % 2 else "金融",
        thesis=f"thesis-{marker}",
        why_selected=f"selected-{marker}",
        entry_plan={"low": 10.0 + rank, "high": 10.2 + rank},
        stop_plan={"price": 9.6 + rank},
        take_profit_plan={"targets": [10.8 + rank, 11.2 + rank]},
        signal={"signal_type": "structure_watch", "marker": marker},
        probability={
            "up_probability_3d": 0.6,
            "evidence": {"nearest_cases": [{"event_id": f"case-{marker}", "marker": marker}]},
        },
        risk={"drawdown_probability": 0.3, "marker": marker},
        ranking={"ranking_score": 0.7, "marker": marker},
        historical_cases=[{"event_id": f"history-{marker}", "marker": marker}],
        decision_context_snapshot_id="dcs_shared",
        explain_context=explain,
    )
    return BoardEntry(
        symbol=symbol,
        name=f"候选{rank}",
        rank=rank,
        final_score=0.9 - rank / 100,
        live_score=0.8 - rank / 100,
        execution_state="watch",
        can_open=False,
        stretched=False,
        invalidated=False,
        action="WATCH",
        entry_zone={"low": 10.0 + rank, "high": 10.2 + rank},
        stop=9.6 + rank,
        take=[10.8 + rank, 11.2 + rank],
        summary=f"summary-{marker}",
        artifact_id="artifact_now",
        style_label="成长",
        pick=pick,
        recommendation_state="TRIGGER_PLAN",
        champion_strategy="pullback",
        score_breakdown={"adaptive": 0.8, "execution": 0.7},
        strategy_context={"marker": marker},
        risk_pack={"main_risks": [f"risk-{marker}"]},
        explain_context=explain,
    )


def _book(entries: list[BoardEntry] | None = None) -> MarketBook:
    board = entries or [_entry(f"600{rank:03d}", rank, marker=f"candidate-{rank}") for rank in range(1, 11)]
    return MarketBook(
        trading_day="20260710",
        book_version="book_now",
        updated_at="2026-07-10T13:00:00+08:00",
        regime={},
        daybook=DayBook(
            trading_day="20260710",
            generated_at="2026-07-10T13:00:00+08:00",
            regime={},
            tradeable=True,
        ),
        board=board,
        artifact_id="artifact_now",
        slot_id="slot_now",
        slot_status="OK",
        publish_allowed=True,
        market_phase="INTRADAY_PM",
        data_status="ok",
    )


def _run(entries: list[BoardEntry], *, run_id: str = "run_active", book_version: str = "book_now") -> AdviceRun:
    return AdviceRun(
        run_id=run_id,
        session_id="s1",
        book_version=book_version,
        created_at="2026-07-10T13:00:00+08:00",
        trading_day="20260710",
        picks=entries,
        artifact_id="artifact_now" if book_version == "book_now" else "artifact_old",
        market_phase="INTRADAY_PM",
        decision_context_snapshot_id="dcs_shared",
    )


def _session(**updates) -> SessionState:
    values = {
        "session_id": "s1",
        "created_at": "t",
        "updated_at": "t",
        "active_run_id": "run_active",
        "focus_subject": {"type": "symbol", "symbol": "600001"},
        "last_focus_symbol": "600001",
        "last_focus_rank": 1,
    }
    values.update(updates)
    return SessionState(**values)


def _assistant_turn(*, blob: str) -> TranscriptEvent:
    return TranscriptEvent(
        seq=2,
        turn_id="turn_1",
        session_id="s1",
        role="assistant",
        content="第一只仍以等待触发为主。",
        created_at="t",
        meta={
            "kind": "recommend",
            "run_id": "run_active",
            "symbols": ["600001", "600002"],
            "message": {
                "message_kind": "recommendation",
                "narrative_text": "第一只仍以等待触发为主。\n后续只在条件满足时执行。",
                "run": {"full_run_blob": blob},
                "picks": [{"full_pick_blob": blob}],
            },
            "right_panel": {"full_panel_blob": blob},
        },
    )


def _tool_step(name: str, arguments: dict) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": f"call_{name}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
            }
        ],
        "reasoning_content": "hidden",
    }


def test_routing_context_deduplicates_heavy_history_and_preserves_refs(monkeypatch):
    book = _book()
    run = _run(book.board)
    marker = "FULL_HISTORY_BLOB_" + "x" * 700_000
    monkeypatch.setattr(context_engine, "load_run", lambda run_id: run if run_id == "run_active" else None)

    context = context_engine.build_agent_routing_context(
        {
            "session": _session(),
            "recent_turns": [_assistant_turn(blob=marker)],
            "recent_claims": [],
        },
        book,
    )

    encoded = json.dumps(context, ensure_ascii=False)
    assert "FULL_HISTORY_BLOB" not in encoded
    assert "recent_turns" not in context
    assert "recent_structured_messages" not in context
    assert context["recent_dialogue"][0]["message_kind"] == "recommendation"
    assert context["recent_dialogue"][0]["run_id"] == "run_active"
    assert context["active_run"]["candidate_source"] == "candidate_summary"
    assert "candidate_summary" not in context["active_run"]
    assert len(context["candidate_summary"]) == 10
    assert serialized_size_bytes(context) < ROUTING_PAYLOAD_LIMIT_BYTES
    assert any(ref.get("decision_context_snapshot_id") == "dcs_shared" for ref in context["context_refs"])


def test_routing_candidate_summary_keeps_decision_fields_without_full_evidence(monkeypatch):
    book = _book()
    run = _run(book.board)
    monkeypatch.setattr(context_engine, "load_run", lambda run_id: run if run_id == "run_active" else None)

    context = context_engine.build_agent_routing_context(
        {"session": _session(), "recent_turns": [], "recent_claims": []},
        book,
    )
    first = context["candidate_summary"][0]

    for key in (
        "adaptive_score",
        "calibrated_probability",
        "recommendation_strength",
        "entry",
        "stop",
        "take",
        "main_risks",
        "missing_features",
        "why_selected",
        "context_ref",
    ):
        assert key in first
    for forbidden in ("probability", "risk", "historical_cases", "explain_context", "feature_snapshot"):
        assert forbidden not in first
    assert first["context_ref"] == {
        "run_id": "run_active",
        "artifact_id": "artifact_now",
        "book_version": "book_now",
        "decision_context_snapshot_id": "dcs_shared",
        "symbol": "600001",
        "rank": 1,
    }


def test_tool_evidence_expands_only_target_and_snapshot_symbol(monkeypatch):
    first = _entry("600001", 1, marker="TARGET_MARKER")
    second = _entry("600002", 2, marker="NON_TARGET_MARKER")
    book = _book([first, second])
    run = _run(book.board)
    snapshot_calls = []

    def fake_snapshot(snapshot_id: str):
        snapshot_calls.append(snapshot_id)
        return {
            "candidate_list": [
                {"symbol": "600001", "adaptive_score": 0.91, "marker": "TARGET_SNAPSHOT"},
                {"symbol": "600002", "adaptive_score": 0.11, "marker": "NON_TARGET_SNAPSHOT"},
            ],
            "probability_output": {
                "600001": {"up_probability_3d": 0.71},
                "600002": {"up_probability_3d": 0.31},
            },
            "risk_output": {"600001": {"risk": "target"}, "600002": {"risk": "other"}},
            "ranking_output": {"details": {"600001": {"rank": 1}, "600002": {"rank": 2}}},
            "historical_cases": {
                "600001": [{"marker": "TARGET_HISTORY"}],
                "600002": [{"marker": "NON_TARGET_HISTORY"}],
            },
        }

    monkeypatch.setattr(context_engine, "load_decision_snapshot", fake_snapshot)
    frame = TurnFrame(
        frame_id="f1",
        raw_message="第一只为什么能进",
        subject="pick",
        request="pick_detail",
        freshness="active_run",
        references={"rank": 1, "symbol": "600001"},
    )
    evidence = EvidencePack(
        frame=frame,
        session=_session(),
        book=book,
        active_run=run,
        subject_entry=first,
    )
    judgment = Judgment(kind="pick_detail", summary="target", subject_entry=first)

    context = context_engine.build_tool_evidence_context(frame, evidence, judgment, [])
    encoded = json.dumps(context, ensure_ascii=False)

    assert snapshot_calls == ["dcs_shared"]
    assert len(context["candidate_details"]) == 1
    detail = context["candidate_details"][0]
    assert detail["identity"]["symbol"] == "600001"
    assert detail["explain_context"]["detail_marker"] == "TARGET_MARKER"
    assert detail["adaptive"]["adaptive_score"] is not None
    assert detail["probability"]["up_probability_3d"] == 0.6
    assert detail["snapshot_resolution"]["loaded"] is True
    assert "NON_TARGET_MARKER" not in encoded
    assert "NON_TARGET_SNAPSHOT" not in encoded
    assert "NON_TARGET_HISTORY" not in encoded
    assert "ranked_board_full_context" not in encoded


def test_compare_and_run_change_expand_only_resolved_candidates(monkeypatch):
    first = _entry("600001", 1, marker="FIRST")
    second = _entry("600002", 2, marker="SECOND")
    third = _entry("600003", 3, marker="THIRD")
    book = _book([first, second, third])
    current = _run([first, third], run_id="run_current")
    previous = _run([first.model_copy(update={"rank": 2}), second], run_id="run_previous", book_version="book_old")
    monkeypatch.setattr(context_engine, "load_decision_snapshot", lambda snapshot_id: None)

    compare_frame = TurnFrame(
        frame_id="compare",
        raw_message="前两只比较",
        subject="compare_set",
        request="candidate_compare",
        freshness="active_run",
    )
    compare_evidence = EvidencePack(
        frame=compare_frame,
        session=_session(active_run_id="run_current"),
        book=book,
        active_run=current,
        compare_entries=[first, second],
    )
    compare_judgment = Judgment(
        kind="candidate_compare",
        summary="compare",
        run=current,
        compare_entries=[first, second],
    )
    compare_context = context_engine.build_tool_evidence_context(
        compare_frame,
        compare_evidence,
        compare_judgment,
        [],
    )
    assert {item["identity"]["symbol"] for item in compare_context["candidate_details"]} == {"600001", "600002"}
    assert "THIRD" not in json.dumps(compare_context, ensure_ascii=False)

    change_frame = TurnFrame(
        frame_id="change",
        raw_message="这次为什么变了",
        subject="run",
        request="run_change",
        freshness="active_run",
    )
    change_evidence = EvidencePack(
        frame=change_frame,
        session=_session(active_run_id="run_current", previous_run_id="run_previous"),
        book=book,
        active_run=current,
        previous_run=previous,
    )
    change_judgment = Judgment(
        kind="run_change",
        summary="changed",
        run=current,
        run_change_view=RunChangeArtifact(
            current_run_id="run_current",
            previous_run_id="run_previous",
            added=["600003"],
            removed=["600002"],
            rank_changes=[{"symbol": "600001", "from": 2, "to": 1}],
        ),
    )
    change_context = context_engine.build_tool_evidence_context(
        change_frame,
        change_evidence,
        change_judgment,
        [],
    )
    details = change_context["run_change_details"]
    assert {item["identity"]["symbol"] for item in details["current_candidates"]} == {"600001", "600003"}
    assert {item["identity"]["symbol"] for item in details["previous_candidates"]} == {"600001", "600002"}


def test_analyze_symbol_and_exit_contexts_expand_only_required_business_data(monkeypatch):
    target = _entry("600001", 1, marker="EXIT_TARGET")
    book = _book([target])
    run = _run([target])
    monkeypatch.setattr(context_engine, "load_decision_snapshot", lambda snapshot_id: None)

    symbol_frame = TurnFrame(
        frame_id="symbol",
        raw_message="688001 怎么看",
        subject="symbol",
        request="single_stock_query",
        freshness="active_run",
        references={"symbol": "688001"},
    )
    symbol_evidence = EvidencePack(frame=symbol_frame, session=_session(), book=book)
    symbol_judgment = Judgment(
        kind="single_stock_query",
        summary="outside current run",
        single_stock_analysis=SingleStockAnalysisArtifact(
            symbol="688001",
            name="外部标的",
            trade_plan={"entry": 10.0, "stop": 9.5},
            overall_state="WATCH",
            reason_codes=["daily_structure_only"],
        ),
    )
    symbol_context = context_engine.build_tool_evidence_context(
        symbol_frame,
        symbol_evidence,
        symbol_judgment,
        [],
    )
    assert symbol_context["candidate_details"] == []
    assert symbol_context["judgment_result"]["artifact"]["type"] == "single_stock_analysis"
    assert symbol_context["judgment_result"]["artifact"]["value"]["symbol"] == "688001"

    exit_frame = TurnFrame(
        frame_id="exit",
        raw_message="第一只已经持有，该不该卖",
        subject="holding",
        request="exit_decision",
        freshness="active_run",
        references={"symbol": "600001", "rank": 1},
        constraints={"position_context": "成本 11.2"},
    )
    exit_evidence = EvidencePack(
        frame=exit_frame,
        session=_session(),
        book=book,
        active_run=run,
        subject_entry=target,
        portfolio_slice={"positions": [{"symbol": "600001", "cost": 11.2}]},
    )
    exit_judgment = Judgment(
        kind="exit_decision",
        summary="hold with stop",
        subject_entry=target,
        exit_decision=ExitDecisionArtifact(
            symbol="600001",
            action="HOLD",
            reason="thesis intact",
            trigger="close below stop",
            stop=10.6,
        ),
    )
    exit_context = context_engine.build_tool_evidence_context(exit_frame, exit_evidence, exit_judgment, [])
    assert [item["identity"]["symbol"] for item in exit_context["candidate_details"]] == ["600001"]
    assert exit_context["position_context"]["positions"][0]["cost"] == 11.2
    assert exit_context["judgment_result"]["artifact"]["type"] == "exit_decision"


def test_every_agent_round_stays_under_routing_budget_with_heavy_history(monkeypatch):
    book = _book()
    run = _run(book.board)
    marker = "AGENT_HISTORY_BLOB_" + "z" * 700_000
    memory = {
        "session": _session(),
        "recent_turns": [_assistant_turn(blob=marker)],
        "recent_claims": [],
    }
    sizes = []
    payload_texts = []

    class FakeLLM:
        agent_model = "fake-agent"

        def __init__(self):
            self.calls = 0

        def available(self):
            return True, "ok"

        def agent_tool_step(self, messages, tools, tool_choice="required", temperature=0.0):
            payload = {
                "model": self.agent_model,
                "messages": messages,
                "temperature": temperature,
                "stream": False,
                "tools": tools,
                "tool_choice": tool_choice,
            }
            sizes.append(serialized_size_bytes(payload))
            payload_texts.append(json.dumps(payload, ensure_ascii=False))
            self.calls += 1
            if self.calls == 1:
                return _tool_step("get_active_run", {"top_n": 10})
            return _tool_step("answer_chat", {"answer": "已读取。", "reason": "done"})

    monkeypatch.setattr(turn_loop, "LLMClient", FakeLLM)
    monkeypatch.setattr(turn_loop, "load_memory_context", lambda session_id: memory)
    monkeypatch.setattr(turn_loop, "load_current_book", lambda: book)
    monkeypatch.setattr(turn_loop, "load_run", lambda run_id: run)
    monkeypatch.setattr(context_engine, "load_run", lambda run_id: run)
    monkeypatch.setattr(turn_loop, "commit_turn", lambda **kwargs: None)

    out = turn_loop.run_turn_sync("s1", "继续")

    assert out["reply"] == "已读取。"
    assert len(sizes) == 2
    assert max(sizes) <= ROUTING_PAYLOAD_LIMIT_BYTES
    assert all("AGENT_HISTORY_BLOB" not in payload for payload in payload_texts)


def test_tool_evidence_narration_payload_stays_under_budget(monkeypatch):
    book = _book()
    run = _run(book.board)
    monkeypatch.setattr(context_engine, "load_decision_snapshot", lambda snapshot_id: None)
    frame = TurnFrame(
        frame_id="recommend",
        raw_message="今天给我10只",
        subject="run",
        request="recommend",
        freshness="active_run",
        constraints={"topk": 10},
    )
    evidence = EvidencePack(frame=frame, session=_session(), book=book)
    judgment = Judgment(kind="recommend", summary="recommend", run=run)

    context = context_engine.build_tool_evidence_context(frame, evidence, judgment, [])
    payload = LLMClient.build_payload(
        "deepseek-chat",
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps({"tool_evidence_context": context}, ensure_ascii=False)},
        ],
    )

    assert len(context["candidate_details"]) == 10
    assert serialized_size_bytes(payload) <= TOOL_EVIDENCE_PAYLOAD_LIMIT_BYTES


def test_context_size_report_contains_sizes_and_refs_but_not_content():
    secret = "PRIVATE_NARRATIVE_SHOULD_NOT_LEAK"
    payload = {
        "model": "test",
        "messages": [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context": {
                            "secret": secret,
                            "context_refs": [
                                {
                                    "run_id": "run_1",
                                    "artifact_id": "artifact_1",
                                    "symbol": "600001",
                                    "rank": 1,
                                }
                            ],
                        }
                    },
                    ensure_ascii=False,
                ),
            }
        ],
    }

    report = context_size_report(payload, stage="agent_routing", limit_bytes=600_000, compressed=True)
    encoded_report = json.dumps(report, ensure_ascii=False)

    assert report["blocks"]
    assert any(block["name"].endswith("context") for block in report["blocks"])
    assert report["context_refs"][0]["run_id"] == "run_1"
    assert secret not in encoded_report


@pytest.mark.parametrize(
    ("limit", "content_size"),
    [
        (300, 2_000),
        (None, LLM_HARD_CAP_BYTES + 100),
    ],
)
def test_llm_budget_rejects_before_http(monkeypatch, limit, content_size):
    posted = []
    monkeypatch.setattr("gp_assistant.llm.client.requests.post", lambda *args, **kwargs: posted.append((args, kwargs)))
    client = LLMClient(base_url="https://example.invalid/v1", api_key="test", model="test")

    with pytest.raises(LLMPayloadBudgetExceeded) as exc_info:
        client.chat(
            [{"role": "user", "content": "x" * content_size}],
            budget_stage="tool_evidence" if limit else "llm_chat",
            payload_limit_bytes=limit,
            payload_compressed=True,
        )

    assert posted == []
    assert exc_info.value.detail()["code"] == "llm_payload_budget_exceeded"
    assert exc_info.value.detail()["budget_report"]["blocks"]


def test_agent_tool_step_applies_fixed_routing_budget_before_http(monkeypatch):
    posted = []
    monkeypatch.setattr("gp_assistant.llm.client.requests.post", lambda *args, **kwargs: posted.append((args, kwargs)))
    client = LLMClient(base_url="https://example.invalid/v1", api_key="test", model="test")

    with pytest.raises(LLMPayloadBudgetExceeded) as exc_info:
        client.agent_tool_step(
            [{"role": "user", "content": "x" * ROUTING_PAYLOAD_LIMIT_BYTES}],
            [],
        )

    assert posted == []
    assert exc_info.value.stage == "agent_routing"
    assert exc_info.value.limit_bytes == ROUTING_PAYLOAD_LIMIT_BYTES


def test_build_reply_does_not_swallow_payload_budget_error(monkeypatch):
    book = _book([_entry("600001", 1)])
    frame = TurnFrame(
        frame_id="chat",
        raw_message="你好",
        subject="market",
        request="chat",
        freshness="active_run",
    )
    evidence = EvidencePack(frame=frame, session=_session(active_run_id=None), book=book)
    judgment = Judgment(kind="chat", summary="chat")
    error = LLMPayloadBudgetExceeded(
        stage="tool_evidence",
        actual_bytes=1_900_000,
        limit_bytes=TOOL_EVIDENCE_PAYLOAD_LIMIT_BYTES,
        budget_report={"stage": "tool_evidence", "blocks": []},
    )
    monkeypatch.setattr("gp_assistant.runtime.narrator.render_reply", lambda payload: (_ for _ in ()).throw(error))

    with pytest.raises(LLMPayloadBudgetExceeded):
        build_reply(session_id="s1", frame=frame, evidence=evidence, judgment=judgment)
