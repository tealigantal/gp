from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from gp_assistant.contracts.objects import AgentToolResult, DayBook, Judgment, MarketBook, SessionState, TurnFrame
from gp_assistant.runtime import turn_loop


def _book() -> MarketBook:
    return MarketBook(
        trading_day="20260429",
        book_version="book_now",
        updated_at="t",
        regime={},
        daybook=DayBook(trading_day="20260428", generated_at="t", regime={}, tradeable=True),
        board=[],
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


def _frame(request: str) -> TurnFrame:
    subject = "run" if request == "recommend" else "symbol"
    refs = {} if request == "recommend" else {"symbol": "600519"}
    return TurnFrame(
        frame_id=f"frame_{request}",
        raw_message=f"{request} please",
        subject=subject,
        request=request,
        freshness="active_run",
        references=refs,
        constraints={"topk": 3} if request == "recommend" else {},
        ambiguity={"confidence": 0.9, "notes": [], "needs_clarification": False},
    )


@pytest.mark.parametrize(
    ("request_type", "tool_name", "message_kind"),
    [
        ("recommend", "get_recommendation", "recommend"),
        ("pick_detail", "get_pick_detail", "pick_detail"),
        ("single_stock_query", "get_single_stock_analysis", "single_stock_query"),
    ],
)
def test_business_card_tool_final_reply_uses_llm_explanation(monkeypatch, request_type, tool_name, message_kind):
    book = _book()
    frame = _frame(request_type)
    session = SessionState(session_id="s1", created_at="t", updated_at="t")
    fallback_text = "后端结构摘要：买入区待确认，止损待确认，止盈待确认。"
    llm_text = "这张卡片的结论是先按计划观察，因为评分、买入区和风险边界共同说明执行条件还需要确认。"
    committed = {}
    tool_calls: list[str] = []

    class _LLM:
        def available(self):
            return True, None

        def run_chat_with_tools(self, messages, tools, temperature=0.0):
            name = tools[0]["function"]["name"]
            tool_calls.append(name)
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": name, "type": "function", "function": {"name": name, "arguments": "{}"}}],
            }

        def chat(self, messages, temperature=0.2, json_mode=False, **kwargs):
            if json_mode:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "is_explaining_card": True,
                                        "grounded_to_card": True,
                                        "needs_repair": False,
                                        "reason": "grounded",
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }
            return {"choices": [{"message": {"content": llm_text}}]}

    def _business_tool(*, tool_name: str, **kwargs):
        assert tool_name == tool_name_expected
        return (
            AgentToolResult(
                tool_name=tool_name,
                reply_text=fallback_text,
                message={"message_kind": message_kind, "narrative_text": fallback_text, "followup_suggestions": []},
                symbols=["600519"],
            ),
            Judgment(kind=message_kind, summary="summary"),
        )

    tool_name_expected = tool_name
    monkeypatch.setattr(turn_loop, "LLMClient", _LLM)
    monkeypatch.setattr(turn_loop, "load_memory_context", lambda session_id: {"session": session, "recent_turns": []})
    monkeypatch.setattr(turn_loop, "load_current_book", lambda: book)
    monkeypatch.setattr(turn_loop, "parse_concern", lambda memory_ctx, loaded_book, user_message: frame)
    monkeypatch.setattr(turn_loop, "load_repair_status_snapshot", lambda: None)
    monkeypatch.setattr(turn_loop, "_business_tool", _business_tool)
    monkeypatch.setattr(turn_loop, "validate_reply", lambda reply, judgment: None)
    monkeypatch.setattr(turn_loop, "commit_turn", lambda **kwargs: committed.setdefault("reply", kwargs["reply"]))

    out = turn_loop.run_turn_sync(session_id="s1", user_message=frame.raw_message)

    assert tool_name in tool_calls
    assert out["reply"] == llm_text
    assert out["reply"] != fallback_text
    assert out["message"]["narrative_text"] == llm_text
    assert committed["reply"].text == llm_text


def test_business_card_tool_accepts_short_grounded_llm_explanation(monkeypatch):
    book = _book()
    frame = _frame("single_stock_query")
    session = SessionState(session_id="s1", created_at="t", updated_at="t")
    fallback_text = "后端结构摘要：买入区待确认，止损待确认，止盈待确认。"
    llm_text = "600519 先观察。"

    class _LLM:
        def available(self):
            return True, None

        def run_chat_with_tools(self, messages, tools, temperature=0.0):
            name = tools[0]["function"]["name"]
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": name, "type": "function", "function": {"name": name, "arguments": "{}"}}],
            }

        def chat(self, messages, temperature=0.2, json_mode=False, **kwargs):
            if json_mode:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "is_explaining_card": True,
                                        "grounded_to_card": True,
                                        "needs_repair": False,
                                        "reason": "short but grounded",
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }
            return {"choices": [{"message": {"content": llm_text}}]}

    monkeypatch.setattr(turn_loop, "LLMClient", _LLM)
    monkeypatch.setattr(turn_loop, "load_memory_context", lambda session_id: {"session": session, "recent_turns": []})
    monkeypatch.setattr(turn_loop, "load_current_book", lambda: book)
    monkeypatch.setattr(turn_loop, "parse_concern", lambda memory_ctx, loaded_book, user_message: frame)
    monkeypatch.setattr(turn_loop, "load_repair_status_snapshot", lambda: None)
    monkeypatch.setattr(
        turn_loop,
        "_business_tool",
        lambda **kwargs: (
            AgentToolResult(
                tool_name="get_single_stock_analysis",
                reply_text=fallback_text,
                message={"message_kind": "single_stock_query", "narrative_text": fallback_text, "symbol": "600519"},
                symbols=["600519"],
            ),
            Judgment(kind="single_stock_query", summary="summary"),
        ),
    )
    monkeypatch.setattr(turn_loop, "validate_reply", lambda reply, judgment: None)
    monkeypatch.setattr(turn_loop, "commit_turn", lambda **kwargs: None)

    out = turn_loop.run_turn_sync(session_id="s1", user_message=frame.raw_message)

    assert out["reply"] == llm_text
    assert out["message"]["narrative_text"] == llm_text


def test_business_card_tool_repairs_once_when_quality_checker_rejects_first_text(monkeypatch):
    book = _book()
    frame = _frame("recommend")
    session = SessionState(session_id="s1", created_at="t", updated_at="t")
    fallback_text = "今天优先看 2 只。"
    repaired_text = "这张推荐卡片指向 600519，因为它在当前计划里排在前面，执行上仍要看买入区和风险边界。"
    quality_calls = 0
    free_text_calls = 0

    class _LLM:
        def available(self):
            return True, None

        def run_chat_with_tools(self, messages, tools, temperature=0.0):
            name = tools[0]["function"]["name"]
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": name, "type": "function", "function": {"name": name, "arguments": "{}"}}],
            }

        def chat(self, messages, temperature=0.2, json_mode=False, **kwargs):
            nonlocal quality_calls, free_text_calls
            if json_mode:
                quality_calls += 1
                passed = quality_calls >= 2
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "is_explaining_card": passed,
                                        "grounded_to_card": passed,
                                        "needs_repair": not passed,
                                        "reason": "ok" if passed else "too shallow",
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }
            free_text_calls += 1
            text = "好的。" if free_text_calls == 1 else repaired_text
            return {"choices": [{"message": {"content": text}}]}

    monkeypatch.setattr(turn_loop, "LLMClient", _LLM)
    monkeypatch.setattr(turn_loop, "load_memory_context", lambda session_id: {"session": session, "recent_turns": []})
    monkeypatch.setattr(turn_loop, "load_current_book", lambda: book)
    monkeypatch.setattr(turn_loop, "parse_concern", lambda memory_ctx, loaded_book, user_message: frame)
    monkeypatch.setattr(turn_loop, "load_repair_status_snapshot", lambda: None)
    monkeypatch.setattr(
        turn_loop,
        "_business_tool",
        lambda **kwargs: (
            AgentToolResult(
                tool_name="get_recommendation",
                reply_text=fallback_text,
                message={"message_kind": "recommend", "narrative_text": fallback_text, "picks": [{"symbol": "600519", "rank": 1}]},
                symbols=["600519"],
            ),
            Judgment(kind="recommend", summary="summary"),
        ),
    )
    monkeypatch.setattr(turn_loop, "validate_reply", lambda reply, judgment: None)
    monkeypatch.setattr(turn_loop, "commit_turn", lambda **kwargs: None)

    out = turn_loop.run_turn_sync(session_id="s1", user_message="recommend")

    assert out["reply"] == repaired_text
    assert quality_calls == 2
    assert free_text_calls == 2


@pytest.mark.parametrize("bad_text", ["", "太短"])
def test_business_card_tool_rejects_missing_or_short_llm_explanation(monkeypatch, bad_text):
    book = _book()
    frame = _frame("recommend")
    session = SessionState(session_id="s1", created_at="t", updated_at="t")
    committed = {"called": False}

    class _LLM:
        def __init__(self):
            self.free_text_calls = 0

        def available(self):
            return True, None

        def run_chat_with_tools(self, messages, tools, temperature=0.0):
            name = tools[0]["function"]["name"]
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": name, "type": "function", "function": {"name": name, "arguments": "{}"}}],
            }

        def chat(self, messages, temperature=0.2, json_mode=False, **kwargs):
            if json_mode:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "is_explaining_card": False,
                                        "grounded_to_card": False,
                                        "needs_repair": True,
                                        "reason": "ungrounded",
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }
            self.free_text_calls += 1
            if self.free_text_calls >= 2:
                return {"choices": [{"message": {"content": "仍然无关"}}]}
            return {"choices": [{"message": {"content": bad_text}}]}

    monkeypatch.setattr(turn_loop, "LLMClient", _LLM)
    monkeypatch.setattr(turn_loop, "load_memory_context", lambda session_id: {"session": session, "recent_turns": []})
    monkeypatch.setattr(turn_loop, "load_current_book", lambda: book)
    monkeypatch.setattr(turn_loop, "parse_concern", lambda memory_ctx, loaded_book, user_message: frame)
    monkeypatch.setattr(turn_loop, "load_repair_status_snapshot", lambda: None)
    monkeypatch.setattr(
        turn_loop,
        "_business_tool",
        lambda **kwargs: (
            AgentToolResult(
                tool_name="get_recommendation",
                reply_text="今天优先看 2 只。",
                message={"message_kind": "recommend", "narrative_text": "今天优先看 2 只。"},
            ),
            Judgment(kind="recommend", summary="summary"),
        ),
    )
    monkeypatch.setattr(turn_loop, "commit_turn", lambda **kwargs: committed.update(called=True))

    with pytest.raises(RuntimeError, match="LLM explanation missing or ungrounded"):
        turn_loop.run_turn_sync(session_id="s1", user_message="recommend")

    assert committed["called"] is False


def test_business_card_tool_propagates_llm_explanation_error_without_commit(monkeypatch):
    book = _book()
    frame = _frame("recommend")
    session = SessionState(session_id="s1", created_at="t", updated_at="t")
    committed = {"called": False}

    class _LLM:
        def available(self):
            return True, None

        def run_chat_with_tools(self, messages, tools, temperature=0.0):
            name = tools[0]["function"]["name"]
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": name, "type": "function", "function": {"name": name, "arguments": "{}"}}],
            }

        def chat(self, messages, temperature=0.2, json_mode=False, **kwargs):
            raise RuntimeError("final narration failed")

    monkeypatch.setattr(turn_loop, "LLMClient", _LLM)
    monkeypatch.setattr(turn_loop, "load_memory_context", lambda session_id: {"session": session, "recent_turns": []})
    monkeypatch.setattr(turn_loop, "load_current_book", lambda: book)
    monkeypatch.setattr(turn_loop, "parse_concern", lambda memory_ctx, loaded_book, user_message: frame)
    monkeypatch.setattr(turn_loop, "load_repair_status_snapshot", lambda: None)
    monkeypatch.setattr(
        turn_loop,
        "_business_tool",
        lambda **kwargs: (
            AgentToolResult(
                tool_name="get_recommendation",
                reply_text="今天优先看 2 只。",
                message={"message_kind": "recommend", "narrative_text": "今天优先看 2 只。"},
            ),
            Judgment(kind="recommend", summary="summary"),
        ),
    )
    monkeypatch.setattr(turn_loop, "commit_turn", lambda **kwargs: committed.update(called=True))

    with pytest.raises(RuntimeError, match="final narration failed"):
        turn_loop.run_turn_sync(session_id="s1", user_message="recommend")

    assert committed["called"] is False


def test_repair_blocking_result_does_not_require_card_llm_explanation(monkeypatch):
    book = _book()
    frame = _frame("recommend")
    session = SessionState(session_id="s1", created_at="t", updated_at="t")
    committed = {"called": False}

    monkeypatch.setattr(turn_loop, "load_memory_context", lambda session_id: {"session": session, "recent_turns": []})
    monkeypatch.setattr(turn_loop, "load_current_book", lambda: book)
    monkeypatch.setattr(turn_loop, "parse_concern", lambda memory_ctx, loaded_book, user_message: frame)
    monkeypatch.setattr(
        turn_loop,
        "load_repair_status_snapshot",
        lambda: SimpleNamespace(
            repair_status="blocked",
            repair_stage="repair_intraday",
            market_phase="INTRADAY_PM",
            daily_target_day="20260428",
            pulse_target_trade_day="20260429",
            pulse_target_slot_at="2026-04-29 14:15:00",
            blocking_reason="repair blocked",
        ),
    )
    monkeypatch.setattr(turn_loop, "validate_reply", lambda reply, judgment: None)
    monkeypatch.setattr(turn_loop, "commit_turn", lambda **kwargs: committed.update(called=True))

    out = turn_loop.run_turn_sync(session_id="s1", user_message="recommend")

    assert out["message"]["message_kind"] == "chat"
    assert "暂不发布正式市场结论" in out["reply"]
    assert committed["called"] is True
