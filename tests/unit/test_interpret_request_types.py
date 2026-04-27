from __future__ import annotations

import json

from gp_assistant.contracts.objects import AdvicePick, BoardEntry, DayBook, MarketBook, ReplyBundle
from gp_assistant.gateway.sessions import get_session_payload, sanitize_chat_payload
from gp_assistant.judgment.chat import judge_chat
from gp_assistant.memory.service import commit_turn
from gp_assistant.runtime.concern_parser import parse_concern
from gp_assistant.runtime.evidence_planner import plan_evidence
from gp_assistant.runtime.turn_loop import build_evidence_pack


def _dummy_book() -> MarketBook:
    pick = AdvicePick(symbol="600519", name="贵州茅台", rank=1, strategy_id="s01", thesis="")
    entry = BoardEntry(
        symbol="600519",
        name="贵州茅台",
        rank=1,
        final_score=1.0,
        live_score=1.0,
        execution_state="watch",
        can_open=False,
        stretched=False,
        invalidated=False,
        summary="观察候选",
        style_label=None,
        pick=pick,
        pulse=None,
    )
    daybook = DayBook(trading_day="20260101", generated_at="2026-01-01T00:00:00Z")
    return MarketBook(
        trading_day="20260101",
        book_version="v1",
        updated_at="2026-01-01T00:00:00Z",
        daybook=daybook,
        board=[entry],
        watchset=[],
        symbol_states={},
        portfolio_snapshot={},
        last_closed_5m=None,
        side_results=[],
        regime={},
        market_phase="POSTCLOSE_PENDING",
        slot_status="DEGRADED",
        publish_allowed=False,
    )


def _memory_ctx():
    from gp_assistant.contracts.objects import SessionState
    from gp_assistant.runtime.utils import now_iso

    return {
        "session": SessionState(session_id="test", created_at=now_iso(), updated_at=now_iso()),
        "recent_turns": [],
        "recent_claims": [],
    }


def _mock_llm(monkeypatch, content_obj: dict):
    from gp_assistant.llm import client as client_mod
    from gp_assistant.llm import interpret as interpret_mod

    class DummyLLM:
        def available(self):
            return True, "ok"

        def chat(self, messages, json_mode=False, **kwargs):
            return {"choices": [{"message": {"content": json.dumps(content_obj, ensure_ascii=False)}}]}

    monkeypatch.setattr(client_mod, "LLMClient", lambda *a, **k: DummyLLM())
    monkeypatch.setattr(interpret_mod, "LLMClient", DummyLLM)


def test_greeting_goes_to_chat(monkeypatch):
    _mock_llm(
        monkeypatch,
        {
            "subject": "market",
            "request": "chat",
            "freshness": "active_run",
            "references": {},
            "constraints": {},
            "ambiguity": {"confidence": 0.9, "notes": [], "needs_clarification": False},
        },
    )
    frame = parse_concern(_memory_ctx(), _dummy_book(), "你好")
    assert frame.request == "chat"


def test_clean_chinese_topk_request_goes_to_recommend():
    frame = parse_concern(_memory_ctx(), _dummy_book(), "今天给我 3 只")
    assert frame.request == "recommend"
    assert frame.constraints.get("topk") == 3


def test_rank_detail_request_does_not_turn_into_recommend():
    frame = parse_concern(_memory_ctx(), _dummy_book(), "第二只为什么")
    assert frame.request == "pick_detail"
    assert frame.references.get("rank") == 2


def test_stop_take_request_prefers_pick_detail():
    frame = parse_concern(_memory_ctx(), _dummy_book(), "002371 的止盈止损点")
    assert frame.request == "pick_detail"
    assert frame.references.get("symbol") == "002371"


def test_exit_request():
    frame = parse_concern(_memory_ctx(), _dummy_book(), "600519 现在该不该卖")
    assert frame.request == "exit_decision"
    assert frame.references.get("symbol") == "600519"


def test_fuzzy_live_request_maps_to_live_entry_check():
    frame = parse_concern(_memory_ctx(), _dummy_book(), "现在是不是先别碰")
    assert frame.request in {"live_entry_check", "no_trade_explain"}


def test_postclose_topk_maps_to_next_session_plan():
    frame = parse_concern(_memory_ctx(), _dummy_book(), "收盘了也给我三只")
    assert frame.request == "recommend"
    assert frame.freshness == "next_session_plan"


def test_llm_unavailable_falls_back_to_recommend(monkeypatch):
    from gp_assistant.llm import client as client_mod
    from gp_assistant.llm import interpret as interpret_mod

    class DummyLLM:
        def available(self):
            return False, "LLM_API_KEY missing"

    monkeypatch.setattr(client_mod, "LLMClient", lambda *a, **k: DummyLLM())
    monkeypatch.setattr(interpret_mod, "LLMClient", DummyLLM)

    frame = parse_concern(_memory_ctx(), _dummy_book(), "今天给我 3 只")
    assert frame.request == "recommend"
    assert frame.constraints.get("topk") == 3


def test_gateway_payload_hides_debug_fields():
    sid = "test_sanitized_payload"
    memory_ctx = _memory_ctx()
    memory_ctx["session"].session_id = sid
    book = _dummy_book()
    frame = parse_concern(memory_ctx, book, "你好")
    plan = plan_evidence(frame)
    evidence = build_evidence_pack(frame, memory_ctx, book, plan)
    judgment = judge_chat()
    reply = ReplyBundle(
        session_id=sid,
        text="你好，我在。",
        kind="chat",
        message={"message_kind": "chat", "narrative_text": "你好，我在。"},
        right_panel={"tradeable": True},
        planner_trace={"frame": frame.model_dump(), "evidence_refs": evidence.evidence_refs},
        evidence_refs=["internal-ref"],
    )
    commit_turn(sid, "你好", reply, judgment)

    session_payload = get_session_payload(sid)
    assistant_turn = next(turn for turn in session_payload["recent_turns"] if turn["role"] == "assistant")
    assert session_payload["recent_claims"] == []
    assert "planner_trace" not in assistant_turn["meta"]

    sanitized = sanitize_chat_payload({"planner_trace": {"x": 1}, "evidence_refs": ["a"], "reply": "ok"})
    assert sanitized["planner_trace"] == {}
    assert sanitized["evidence_refs"] == []
    assert sanitized["reply"] == "ok"
