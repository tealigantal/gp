from __future__ import annotations

from types import SimpleNamespace

import pytest

from gp_assistant.contracts.objects import DayBook, MarketBook, SessionState, TranscriptEvent, TurnFrame
from gp_assistant.runtime import turn_loop


def test_term_explain_result_uses_recent_assistant_message():
    session = SessionState(session_id="s1", created_at="t", updated_at="t", last_focus_symbol="600111")
    turn = TranscriptEvent(
        seq=2,
        turn_id="t1",
        session_id="s1",
        role="assistant",
        content="当前只适合观察，不建议直接进。",
        created_at="t",
        meta={
            "kind": "live_entry_check",
            "message": {
                "message_kind": "live_entry_check",
                "narrative_text": "当前只适合观察，不建议直接进。",
                "live_check": {
                    "symbol": "600111",
                    "execution_state": "WATCH_ONLY",
                    "next_action": "先观察，不做主动追价。",
                    "gate_reasons": ["buyable_count=0", "up_ratio=0.756"],
                },
            },
        },
    )
    book = MarketBook(
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
        market_phase="INTRADAY_PM",
        slot_status="OK",
        daybook_effective_day="20260428",
        pulse_trade_day="20260429",
        pulse_slot_at="2026-04-29 14:10:00",
    )
    frame = TurnFrame(frame_id="f1", raw_message="为什么仅观察", subject="market", request="term_explain", freshness="active_run")

    result = turn_loop._term_explain_result(session_id="s1", memory_ctx={"session": session, "recent_turns": [turn]}, book=book, frame=frame)

    assert result.message["message_kind"] == "term_explain"
    assert "暂时只观察" in result.reply_text
    assert "WATCH_ONLY" not in result.reply_text
    assert "buyable_count=0" not in result.reply_text
    assert result.message["source_symbol"] == "600111"


def test_run_turn_sync_term_explain_bypasses_repair_block(monkeypatch):
    book = MarketBook(
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
    frame = TurnFrame(frame_id="frame1", raw_message="什么是收盘有效跌破支撑带", subject="market", request="term_explain", freshness="active_run")
    session = SessionState(session_id="s1", created_at="t", updated_at="t")
    turn = TranscriptEvent(
        seq=2,
        turn_id="t1",
        session_id="s1",
        role="assistant",
        content="相对同组候选综合条件更优。",
        created_at="t",
        meta={
            "message": {
                "message_kind": "pick_detail",
                "narrative_text": "相对同组候选综合条件更优。",
                "pick": {
                    "symbol": "600111",
                    "entry_text": "46.21 - 51.46",
                    "stop_text": "收盘有效跌破支撑带",
                    "take_text": "59.10 / 60.28",
                },
            }
        },
    )

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

        def chat(self, messages, temperature=0.2):
            return {"choices": [{"message": {"content": "收盘有效跌破支撑带是这轮计划里的止损/失效边界。"}}]}

    monkeypatch.setattr(turn_loop, "LLMClient", _LLM)
    monkeypatch.setattr(turn_loop, "load_memory_context", lambda session_id: {"session": session, "recent_turns": [turn]})
    monkeypatch.setattr(turn_loop, "load_current_book", lambda: book)
    monkeypatch.setattr(turn_loop, "parse_concern", lambda memory_ctx, loaded_book, user_message: frame)
    monkeypatch.setattr(
        turn_loop,
        "load_repair_status_snapshot",
        lambda: SimpleNamespace(
            repair_status="running",
            repair_stage="repair_intraday",
            market_phase="INTRADAY_PM",
            daily_target_day="20260428",
            pulse_target_trade_day="20260429",
            pulse_target_slot_at="2026-04-29 14:15:00",
            blocking_reason="repair in progress",
        ),
    )
    monkeypatch.setattr(turn_loop, "validate_reply", lambda reply, judgment: None)
    monkeypatch.setattr(turn_loop, "commit_turn", lambda **kwargs: None)

    out = turn_loop.run_turn_sync(session_id="s1", user_message="什么是收盘有效跌破支撑带")

    assert out["message"]["message_kind"] == "term_explain"
    assert "收盘有效跌破支撑带" in out["reply"]
    assert "暂不发布正式市场结论" not in out["reply"]


def test_term_explain_finds_older_matching_turn_not_only_latest():
    session = SessionState(session_id="s1", created_at="t", updated_at="t")
    older = TranscriptEvent(
        seq=2,
        turn_id="t-old",
        session_id="s1",
        role="assistant",
        content="older",
        created_at="t",
        meta={
            "message": {
                "message_kind": "pick_detail",
                "narrative_text": "older detail",
                "pick": {
                    "symbol": "600111",
                    "entry_text": "46.21 - 51.46",
                    "stop_text": "收盘有效跌破支撑带",
                    "take_text": "59.10 / 60.28",
                },
            }
        },
    )
    latest = TranscriptEvent(
        seq=4,
        turn_id="t-new",
        session_id="s1",
        role="assistant",
        content="latest",
        created_at="t",
        meta={
            "message": {
                "message_kind": "chat",
                "narrative_text": "这是另一条不相关的回复。",
            }
        },
    )
    book = MarketBook(
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
        market_phase="INTRADAY_PM",
        slot_status="OK",
        daybook_effective_day="20260428",
        pulse_trade_day="20260429",
        pulse_slot_at="2026-04-29 14:10:00",
    )
    frame = TurnFrame(frame_id="f1", raw_message="什么是收盘有效跌破支撑带", subject="market", request="term_explain", freshness="active_run")

    result = turn_loop._term_explain_result(
        session_id="s1",
        memory_ctx={"session": session, "recent_turns": [older, latest]},
        book=book,
        frame=frame,
    )

    assert "收盘有效跌破支撑带" in result.reply_text
    assert "46.21 - 51.46" in result.reply_text


def test_run_turn_sync_tool_agent_failure_does_not_use_legacy_fallback(monkeypatch):
    book = MarketBook(
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
    frame = TurnFrame(
        frame_id="frame1",
        raw_message="recommend",
        subject="run",
        request="recommend",
        freshness="active_run",
        constraints={"topk": 3},
    )
    session = SessionState(session_id="s1", created_at="t", updated_at="t")
    committed = {"called": False}

    class _FailingLLM:
        def available(self):
            return True, None

        def run_chat_with_tools(self, messages, tools, temperature=0.0):
            raise RuntimeError("tool call failed")

    monkeypatch.setattr(turn_loop, "LLMClient", _FailingLLM)
    monkeypatch.setattr(turn_loop, "load_memory_context", lambda session_id: {"session": session, "recent_turns": []})
    monkeypatch.setattr(turn_loop, "load_current_book", lambda: book)
    monkeypatch.setattr(turn_loop, "parse_concern", lambda memory_ctx, loaded_book, user_message: frame)
    monkeypatch.setattr(turn_loop, "load_repair_status_snapshot", lambda: None)

    def _commit_turn(**kwargs):
        committed["called"] = True

    monkeypatch.setattr(turn_loop, "commit_turn", _commit_turn)

    with pytest.raises(RuntimeError, match="tool call failed"):
        turn_loop.run_turn_sync(session_id="s1", user_message="recommend")

    assert committed["called"] is False
