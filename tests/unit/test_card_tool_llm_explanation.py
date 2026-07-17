from __future__ import annotations

import json

import pytest

from gp_assistant.contracts.objects import (
    AdvicePick,
    AdviceRun,
    BoardEntry,
    DayBook,
    EvidencePack,
    MarketBook,
    SessionState,
    TurnFrame,
)
from gp_assistant.judgment.workflow import candidate_compare_workflow
from gp_assistant.llm.semantics import CARD_QUALITY_SYSTEM, CARD_REPAIR_SYSTEM, assess_card_explanation
from gp_assistant.runtime import context_engine, turn_loop
from gp_assistant.runtime.utils import now_iso


def _entry(symbol: str, rank: int, name: str = "示例") -> BoardEntry:
    pick = AdvicePick(
        symbol=symbol,
        name=name,
        rank=rank,
        thesis="结构仍可观察",
        why_selected="综合条件较好",
        entry_plan={"price": 10.0},
        stop_plan={"price": 9.6},
        take_profit_plan={"targets": [10.8]},
    )
    return BoardEntry(
        symbol=symbol,
        name=name,
        rank=rank,
        final_score=0.8,
        live_score=0.7,
        execution_state="watch",
        can_open=False,
        stretched=False,
        invalidated=False,
        summary="观察",
        pick=pick,
    )


def _book() -> MarketBook:
    return MarketBook(
        trading_day="20260429",
        book_version="book_now",
        updated_at="t",
        regime={},
        daybook=DayBook(trading_day="20260428", generated_at="t", regime={}, tradeable=True),
        board=[_entry("600111", 1, "北方稀土"), _entry("600036", 2, "招商银行"), _entry("000063", 3, "中兴通讯")],
        watchset=[],
        symbol_states={},
        portfolio_snapshot={},
        side_results=[],
        artifact_id="artifact_now",
        daybook_effective_day="20260428",
        pulse_trade_day="20260429",
        pulse_slot_at="2026-04-29 14:10:00",
        slot_status="OK",
        market_phase="INTRADAY_PM",
        data_status="ok",
    )


def _run() -> AdviceRun:
    return AdviceRun(
        run_id="run_active",
        session_id="s1",
        book_version="book_now",
        created_at=now_iso(),
        trading_day="20260429",
        picks=[_entry("600111", 1, "北方稀土"), _entry("600036", 2, "招商银行"), _entry("000063", 3, "中兴通讯")],
        artifact_id="artifact_now",
        market_phase="INTRADAY_PM",
    )


def _session() -> SessionState:
    return SessionState(session_id="s1", created_at="t", updated_at="t", active_run_id="run_active")


def _tool_step(name: str, args: dict) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
            }
        ],
        "reasoning_content": "hidden reasoning",
    }


def _mock_final_narration(monkeypatch, text: str = "LLM自然语言回复"):
    monkeypatch.setattr("gp_assistant.runtime.narrator.render_reply", lambda payload: text)


def test_agent_tool_schema_is_strict_and_uses_required_tool_choice():
    tools = turn_loop._agent_tool_schemas()
    compare_tool = next(tool for tool in tools if tool["function"]["name"] == "compare_candidates")
    assert compare_tool["function"]["strict"] is True
    assert compare_tool["function"]["parameters"]["additionalProperties"] is False
    for tool in tools:
        parameters = tool["function"]["parameters"]
        assert set(parameters["required"]) == set(parameters["properties"])

    seen = {}

    class _LLM:
        def available(self):
            return True, "ok"

        def agent_tool_step(self, messages, tools, tool_choice="required", temperature=0.0):
            seen["tool_choice"] = tool_choice
            return _tool_step("answer_chat", {"answer": "你好，可以直接问当前候选。", "reason": "chat"})

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(turn_loop, "LLMClient", _LLM)
        monkeypatch.setattr(turn_loop, "load_memory_context", lambda session_id: {"session": _session(), "recent_turns": [], "recent_claims": []})
        monkeypatch.setattr(turn_loop, "load_current_book", _book)
        monkeypatch.setattr(turn_loop, "commit_turn", lambda **kwargs: None)
        out = turn_loop.run_turn_sync("s1", "你好")
    finally:
        monkeypatch.undo()

    assert seen["tool_choice"] == "required"
    assert out["message"]["message_kind"] == "chat"


def test_agent_selects_compare_candidates_for_technology_request(monkeypatch):
    run = _run()
    session = _session()

    class _LLM:
        def available(self):
            return True, "ok"

        def agent_tool_step(self, messages, tools, tool_choice="required", temperature=0.0):
            return _tool_step(
                "compare_candidates",
                {
                    "symbols": ["600111", "600036", "000063"],
                    "top_n": 3,
                    "selected_symbol": "000063",
                    "selected_rank": 3,
                    "selection_reason": "中兴通讯更符合科技股约束。",
                    "confidence": 0.82,
                    "user_constraint": "科技股",
                    "model_reasoning_summary": "基于名称和通用常识判断。",
                },
            )

    monkeypatch.setattr(turn_loop, "LLMClient", _LLM)
    monkeypatch.setattr(turn_loop, "load_memory_context", lambda session_id: {"session": session, "recent_turns": [], "recent_claims": []})
    monkeypatch.setattr(turn_loop, "load_current_book", _book)
    monkeypatch.setattr(turn_loop, "load_run", lambda run_id: run)
    monkeypatch.setattr(context_engine, "load_run", lambda run_id: run)
    _mock_final_narration(monkeypatch, "LLM自然话：中兴通讯更符合科技股约束。")
    committed = {}
    monkeypatch.setattr(turn_loop, "commit_turn", lambda **kwargs: committed.setdefault("reply", kwargs["reply"]))

    out = turn_loop.run_turn_sync("s1", "科技股，你自己分析一下哪个是，然后输出文字给我，聊天")

    assert out["message"]["message_kind"] == "candidate_compare"
    assert out["message"]["candidate_compare"]["selected_symbol"] == "000063"
    assert "中兴通讯更符合科技股约束" in out["reply"]
    assert committed["reply"].kind == "candidate_compare"


def test_agent_exit_question_uses_exit_decision_workflow(monkeypatch):
    book = _book()
    book.board = [_entry("000063", 1, "中兴通讯"), _entry("600519", 2, "贵州茅台")]
    run = AdviceRun(
        run_id="run_holding",
        session_id="s1",
        book_version="book_now",
        created_at=now_iso(),
        trading_day="20260429",
        picks=book.board,
        artifact_id="artifact_now",
        market_phase="INTRADAY_PM",
    )
    session = _session()

    class _LLM:
        def available(self):
            return True, "ok"

        def agent_tool_step(self, messages, tools, tool_choice="required", temperature=0.0):
            tool_names = {tool["function"]["name"] for tool in tools}
            assert "analyze_exit_decision" in tool_names
            return _tool_step(
                "analyze_exit_decision",
                {
                    "symbol": "600519",
                    "rank": None,
                    "position_context": "我已经持有600519，成本1150，给出卖点",
                },
            )

    monkeypatch.setattr(turn_loop, "LLMClient", _LLM)
    monkeypatch.setattr(turn_loop, "load_memory_context", lambda session_id: {"session": session, "recent_turns": [], "recent_claims": []})
    monkeypatch.setattr(turn_loop, "load_current_book", lambda: book)
    monkeypatch.setattr(turn_loop, "load_run", lambda run_id: run)
    monkeypatch.setattr(context_engine, "load_run", lambda run_id: run)
    _mock_final_narration(monkeypatch, "LLM自然话：先看风控位，再看止盈卖点。")
    monkeypatch.setattr(turn_loop, "commit_turn", lambda **kwargs: None)

    out = turn_loop.run_turn_sync("s1", "我已经持有600519，成本1150，给出卖点")

    assert out["message"]["message_kind"] == "exit_decision"
    assert out["message"]["exit_decision"]["symbol"] == "600519"
    assert "风控位" in out["reply"]


def test_agent_symbol_tool_compare_phrase_normalizes_to_compare(monkeypatch):
    book = _book()
    book.board = [_entry("000063", 1, "中兴通讯"), _entry("600519", 2, "贵州茅台")]
    run = AdviceRun(
        run_id="run_compare",
        session_id="s1",
        book_version="book_now",
        created_at=now_iso(),
        trading_day="20260429",
        picks=book.board,
        artifact_id="artifact_now",
        market_phase="INTRADAY_PM",
    )
    session = _session()

    class _LLM:
        def available(self):
            return True, "ok"

        def agent_tool_step(self, messages, tools, tool_choice="required", temperature=0.0):
            return _tool_step("analyze_symbol", {"symbol": "600519", "question": "600519现在还能买吗，为什么不如第一只"})

    monkeypatch.setattr(turn_loop, "LLMClient", _LLM)
    monkeypatch.setattr(turn_loop, "load_memory_context", lambda session_id: {"session": session, "recent_turns": [], "recent_claims": []})
    monkeypatch.setattr(turn_loop, "load_current_book", lambda: book)
    monkeypatch.setattr(turn_loop, "load_run", lambda run_id: run)
    monkeypatch.setattr(context_engine, "load_run", lambda run_id: run)
    _mock_final_narration(monkeypatch, "LLM自然话：600519 和第一只一起比较。")
    monkeypatch.setattr(turn_loop, "commit_turn", lambda **kwargs: None)

    out = turn_loop.run_turn_sync("s1", "600519现在还能买吗，为什么不如第一只")

    assert out["message"]["message_kind"] == "compare"
    assert set(out["message"]["symbols"]) == {"000063", "600519"}


def test_agent_candidate_compare_merges_explicit_symbol_and_rank(monkeypatch):
    book = _book()
    book.board = [_entry("000063", 1, "中兴通讯"), _entry("600519", 2, "贵州茅台")]
    run = AdviceRun(
        run_id="run_compare",
        session_id="s1",
        book_version="book_now",
        created_at=now_iso(),
        trading_day="20260429",
        picks=book.board,
        artifact_id="artifact_now",
        market_phase="INTRADAY_PM",
    )
    session = _session()

    class _LLM:
        def available(self):
            return True, "ok"

        def agent_tool_step(self, messages, tools, tool_choice="required", temperature=0.0):
            return _tool_step(
                "compare_candidates",
                {
                    "symbols": ["000063"],
                    "top_n": 10,
                    "selected_symbol": "000063",
                    "selected_rank": 1,
                    "selection_reason": "用户问600519为什么不如第一只，需要对比两者。",
                    "confidence": 0.8,
                    "user_constraint": "600519 vs 第一只",
                    "model_reasoning_summary": "比较用户显式标的和排名第一标的。",
                },
            )

    monkeypatch.setattr(turn_loop, "LLMClient", _LLM)
    monkeypatch.setattr(turn_loop, "load_memory_context", lambda session_id: {"session": session, "recent_turns": [], "recent_claims": []})
    monkeypatch.setattr(turn_loop, "load_current_book", lambda: book)
    monkeypatch.setattr(turn_loop, "load_run", lambda run_id: run)
    monkeypatch.setattr(context_engine, "load_run", lambda run_id: run)
    _mock_final_narration(monkeypatch, "LLM自然话：000063 当前优先，600519 暂不如第一只。")
    monkeypatch.setattr(turn_loop, "commit_turn", lambda **kwargs: None)

    out = turn_loop.run_turn_sync("s1", "600519现在还能买吗，为什么不如第一只")

    assert out["message"]["message_kind"] == "candidate_compare"
    assert set(out["message"]["symbols"]) == {"000063", "600519"}
    assert "600519" in out["reply"]


def test_agent_context_includes_compact_ranked_candidate_summary(monkeypatch):
    book = _book()
    book.board = [_entry(f"600{i:03d}", i, f"候选{i}") for i in range(1, 11)]
    session = _session()
    monkeypatch.setattr(context_engine, "load_run", lambda run_id: None)
    ctx = context_engine.build_agent_routing_context({"session": session, "recent_turns": [], "recent_claims": []}, book)

    assert len(ctx["candidate_summary"]) == 10
    assert ctx["candidate_summary"][9]["symbol"] == "600010"
    assert "score_breakdown" not in ctx["candidate_summary"][0]
    assert "context_ref" in ctx["candidate_summary"][0]


def test_candidate_compare_rejects_selection_outside_requested_scope():
    book = _book()
    run = _run()
    frame = TurnFrame(
        frame_id="f1",
        raw_message="前两个里挑一个",
        subject="compare_set",
        request="candidate_compare",
        freshness="active_run",
        references={"selected_symbol": "000063"},
        constraints={"top_n": 2, "selection_reason": "选第三只", "confidence": 0.8},
    )
    evidence = EvidencePack(frame=frame, session=_session(), book=book, active_run=run, compare_entries=run.picks)

    with pytest.raises(ValueError, match="outside candidate scope"):
        candidate_compare_workflow(evidence)


def test_candidate_compare_does_not_select_when_agent_does_not_select():
    book = _book()
    run = _run()
    frame = TurnFrame(
        frame_id="f1",
        raw_message="前两个里比较一下",
        subject="compare_set",
        request="candidate_compare",
        freshness="active_run",
        constraints={"top_n": 2, "selection_reason": "两只风格不同，暂时没有明确优先级。"},
    )
    evidence = EvidencePack(frame=frame, session=_session(), book=book, active_run=run, compare_entries=run.picks)

    judgment = candidate_compare_workflow(evidence)

    assert judgment.candidate_comparison is not None
    assert judgment.candidate_comparison.selected_symbol is None
    assert judgment.subject_entry is None


def test_agent_intraday_situation_discloses_unverified_user_input(monkeypatch):
    run = _run()
    session = _session()

    class _LLM:
        def available(self):
            return True, "ok"

        def agent_tool_step(self, messages, tools, tool_choice="required", temperature=0.0):
            return _tool_step(
                "analyze_intraday_situation",
                {"symbol": "000063", "rank": None, "user_situation": "000063 现在冲到 38.2，最高 38.8，回落横住了还能进吗"},
            )

    def _quote_snapshot(**kwargs):
        return {
            "source": "user",
            "verified": False,
            "status": "user_quote_only",
            "symbol": "000063",
            "current_price": 38.2,
            "day_high": 38.8,
            "user_quote": {"source": "user", "current_price": 38.2, "day_high": 38.8},
        }

    monkeypatch.setattr(turn_loop, "LLMClient", _LLM)
    monkeypatch.setattr(turn_loop, "load_memory_context", lambda session_id: {"session": session, "recent_turns": [], "recent_claims": []})
    monkeypatch.setattr(turn_loop, "load_current_book", _book)
    monkeypatch.setattr(turn_loop, "load_run", lambda run_id: run)
    monkeypatch.setattr(context_engine, "load_run", lambda run_id: run)
    monkeypatch.setattr("gp_assistant.judgment.workflow.build_live_quote_snapshot", _quote_snapshot)
    _mock_final_narration(monkeypatch, "LLM自然话：按你提供的盘中价判断，盘中价未能验证。")
    monkeypatch.setattr(turn_loop, "commit_turn", lambda **kwargs: None)

    out = turn_loop.run_turn_sync("s1", "000063 现在冲到 38.2，最高 38.8，回落横住了还能进吗")

    assert out["message"]["message_kind"] == "intraday_situation"
    assert out["message"]["intraday_situation"]["source"] == "unverified_user_input"
    assert "按你提供" in out["reply"] or "你提供" in out["reply"] or "未能验证" in out["reply"]


def test_parameter_explanation_prompt_contracts_are_present():
    assert "Parameter-quality standards" in CARD_QUALITY_SYSTEM
    assert "needs_repair=true" in CARD_QUALITY_SYSTEM
    assert "slot_rel_vol" in CARD_QUALITY_SYSTEM
    assert "Parameter repair rules" in CARD_REPAIR_SYSTEM
    assert "Do not invent it" in CARD_REPAIR_SYSTEM


def test_quality_checker_rejects_generic_volume_rs_entry_text():
    class _LLM:
        def available(self):
            return True, None

        def chat(self, messages, json_mode=False, temperature=0.0, **kwargs):
            assert json_mode is True
            payload = json.loads(messages[1]["content"])
            assistant_text = payload["assistant_text"]
            needs_repair = "量能和 RS" in assistant_text and "slot_rel_vol" not in assistant_text
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "is_explaining_card": not needs_repair,
                                    "grounded_to_card": not needs_repair,
                                    "needs_repair": needs_repair,
                                    "reason": "generic parameter wording" if needs_repair else "ok",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

    quality = assess_card_explanation(
        card_message={"message_kind": "live_entry_check", "symbol": "600519", "slot_rel_vol": 0.8},
        assistant_text="量能和 RS 配合后再进。",
        fallback_text="fallback",
        client=_LLM(),
    )
    assert quality.needs_repair is True
