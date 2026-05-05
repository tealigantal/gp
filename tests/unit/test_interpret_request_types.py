from __future__ import annotations

import inspect
import json
import logging

import pytest

from gp_assistant.contracts.objects import AdvicePick, BoardEntry, DayBook, MarketBook, ReplyBundle
from gp_assistant.core.errors import IntentLLMUnavailable, IntentParseFailed
from gp_assistant.gateway.sessions import get_session_payload, sanitize_chat_payload
from gp_assistant.judgment.chat import judge_chat
from gp_assistant.memory.service import commit_turn
from gp_assistant.runtime.concern_parser import parse_concern
from gp_assistant.runtime.evidence_planner import plan_evidence
from gp_assistant.runtime.turn_loop import build_evidence_pack


def _dummy_book() -> MarketBook:
    pick = AdvicePick(symbol="600519", name="Moutai", rank=1, strategy_id="s01", thesis="")
    entry = BoardEntry(
        symbol="600519",
        name="Moutai",
        rank=1,
        final_score=1.0,
        live_score=1.0,
        execution_state="watch",
        can_open=False,
        stretched=False,
        invalidated=False,
        summary="watch",
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


def _mock_llm_contents(monkeypatch, contents: list[str]):
    from gp_assistant.llm import client as client_mod
    from gp_assistant.llm import interpret as interpret_mod

    class DummyLLM:
        def __init__(self):
            self.contents = list(contents)

        def available(self):
            return True, "ok"

        def chat(self, messages, json_mode=False, **kwargs):
            content = self.contents.pop(0) if self.contents else contents[-1]
            return {"choices": [{"message": {"content": content}}]}

    instance = DummyLLM()
    monkeypatch.setattr(client_mod, "LLMClient", lambda *a, **k: instance)
    monkeypatch.setattr(interpret_mod, "LLMClient", lambda *a, **k: instance)


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
    frame = parse_concern(_memory_ctx(), _dummy_book(), "hello")
    assert frame.request == "chat"


def test_llm_parsed_recommend_request(monkeypatch):
    _mock_llm(
        monkeypatch,
        {
            "subject": "run",
            "request": "recommend",
            "freshness": "active_run",
            "references": {},
            "constraints": {"topk": 3},
            "ambiguity": {"confidence": 0.9, "notes": [], "needs_clarification": False},
        },
    )
    frame = parse_concern(_memory_ctx(), _dummy_book(), "recommend 3")
    assert frame.request == "recommend"
    assert frame.constraints.get("topk") == 3


def test_llm_parsed_rank_detail_request(monkeypatch):
    _mock_llm(
        monkeypatch,
        {
            "subject": "pick",
            "request": "pick_detail",
            "freshness": "active_run",
            "references": {"rank": 2},
            "constraints": {},
            "ambiguity": {"confidence": 0.9, "notes": [], "needs_clarification": False},
        },
    )
    frame = parse_concern(_memory_ctx(), _dummy_book(), "detail for rank 2")
    assert frame.request == "pick_detail"
    assert frame.references.get("rank") == 2


def test_llm_parsed_symbol_detail_request(monkeypatch):
    _mock_llm(
        monkeypatch,
        {
            "subject": "symbol",
            "request": "pick_detail",
            "freshness": "active_run",
            "references": {"symbol": "002371"},
            "constraints": {},
            "ambiguity": {"confidence": 0.9, "notes": [], "needs_clarification": False},
        },
    )
    frame = parse_concern(_memory_ctx(), _dummy_book(), "detail for 002371")
    assert frame.request == "pick_detail"
    assert frame.references.get("symbol") == "002371"


def test_llm_parsed_exit_request(monkeypatch):
    _mock_llm(
        monkeypatch,
        {
            "subject": "holding",
            "request": "exit_decision",
            "freshness": "latest_5m",
            "references": {"symbol": "600519"},
            "constraints": {},
            "ambiguity": {"confidence": 0.9, "notes": [], "needs_clarification": False},
        },
    )
    frame = parse_concern(_memory_ctx(), _dummy_book(), "exit 600519")
    assert frame.request == "exit_decision"
    assert frame.references.get("symbol") == "600519"


def test_llm_parsed_live_request(monkeypatch):
    _mock_llm(
        monkeypatch,
        {
            "subject": "symbol",
            "request": "live_entry_check",
            "freshness": "latest_5m",
            "references": {"symbol": "600519"},
            "constraints": {},
            "ambiguity": {"confidence": 0.9, "notes": [], "needs_clarification": False},
        },
    )
    frame = parse_concern(_memory_ctx(), _dummy_book(), "live check")
    assert frame.request == "live_entry_check"


def test_llm_parsed_term_explain_request(monkeypatch):
    _mock_llm(
        monkeypatch,
        {
            "subject": "market",
            "request": "term_explain",
            "freshness": "active_run",
            "references": {},
            "constraints": {},
            "ambiguity": {"confidence": 0.92, "notes": [], "needs_clarification": False},
        },
    )
    frame = parse_concern(_memory_ctx(), _dummy_book(), "什么是收盘有效跌破支撑带")
    assert frame.request == "term_explain"


def test_llm_parsed_postclose_plan(monkeypatch):
    _mock_llm(
        monkeypatch,
        {
            "subject": "run",
            "request": "recommend",
            "freshness": "next_session_plan",
            "references": {},
            "constraints": {"topk": 3},
            "ambiguity": {"confidence": 0.9, "notes": [], "needs_clarification": False},
        },
    )
    frame = parse_concern(_memory_ctx(), _dummy_book(), "postclose plan")
    assert frame.request == "recommend"
    assert frame.freshness == "next_session_plan"


def test_llm_unavailable_raises(monkeypatch):
    from gp_assistant.llm import client as client_mod
    from gp_assistant.llm import interpret as interpret_mod

    class DummyLLM:
        def available(self):
            return False, "LLM_API_KEY missing"

    monkeypatch.setattr(client_mod, "LLMClient", lambda *a, **k: DummyLLM())
    monkeypatch.setattr(interpret_mod, "LLMClient", DummyLLM)

    with pytest.raises(IntentLLMUnavailable):
        parse_concern(_memory_ctx(), _dummy_book(), "anything")


def test_invalid_json_rewrite_once_succeeds(monkeypatch):
    valid = {
        "subject": "market",
        "request": "chat",
        "freshness": "active_run",
        "references": {},
        "constraints": {},
        "ambiguity": {"confidence": 0.7, "notes": ["rewritten"], "needs_clarification": False},
    }
    _mock_llm_contents(monkeypatch, ["不是 JSON", json.dumps(valid, ensure_ascii=False)])

    frame = parse_concern(_memory_ctx(), _dummy_book(), "anything")

    assert frame.request == "chat"
    assert frame.ambiguity["notes"] == ["rewritten"]


def test_invalid_json_twice_raises_parse_failed(monkeypatch):
    _mock_llm_contents(monkeypatch, ["不是 JSON", "{still bad"])

    with pytest.raises(IntentParseFailed) as exc_info:
        parse_concern(_memory_ctx(), _dummy_book(), "anything")

    assert exc_info.value.attempts == 2


def test_router_prompt_contract_is_strict_utf8_json():
    from gp_assistant.llm.interpret import SYSTEM
    from gp_assistant.runtime import concern_parser

    assert "严格 JSON" in SYSTEM
    assert "只输出 JSON" in SYSTEM
    assert "不要 Markdown" in SYSTEM
    assert "闲聊、问候、能力咨询使用 chat" in SYSTEM
    for mojibake_fragment in ("浣犳", "闂", "婵", "瑙ｆ瀽", "鎰忓浘"):
        assert mojibake_fragment not in SYSTEM

    source = inspect.getsource(concern_parser)
    assert "quick_parse_concern" not in source
    assert "_fallback_semantic_parse" not in source


@pytest.mark.parametrize(
    ("message", "expected_request"),
    [
        ("止盈怎么计算的", "term_explain"),
        ("这个目标价咋来的", "term_explain"),
        ("继续", "term_explain"),
        ("？", "term_explain"),
        ("你好", "chat"),
    ],
)
def test_llm_semantic_samples_accept_mocked_frames(monkeypatch, message, expected_request):
    _mock_llm(
        monkeypatch,
        {
            "subject": "market" if expected_request == "chat" else "pick",
            "request": expected_request,
            "freshness": "active_run",
            "references": {},
            "constraints": {},
            "ambiguity": {"confidence": 0.9, "notes": [], "needs_clarification": False},
        },
    )

    frame = parse_concern(_memory_ctx(), _dummy_book(), message)

    assert frame.request == expected_request


def test_invalid_json_retry_logs_structured_metadata(monkeypatch, caplog):
    valid = {
        "subject": "market",
        "request": "chat",
        "freshness": "active_run",
        "references": {},
        "constraints": {},
        "ambiguity": {"confidence": 0.7, "notes": ["rewritten"], "needs_clarification": False},
    }
    _mock_llm_contents(monkeypatch, ["not JSON", json.dumps(valid, ensure_ascii=False)])
    caplog.set_level(logging.INFO, logger="gp_assistant.llm.interpret")

    frame = parse_concern(_memory_ctx(), _dummy_book(), "hello")

    assert frame.request == "chat"
    retry = next(record for record in caplog.records if record.message == "intent_parse_retry")
    assert retry.retry_count == 1
    assert retry.parse_error_type == "JSONDecodeError"
    success = next(record for record in caplog.records if record.message == "intent_parse_success")
    assert success.intent_request == "chat"
    assert success.intent_subject == "market"
    assert success.retry_count == 1
    assert not hasattr(retry, "raw_output")


def test_gateway_payload_hides_internal_tool_trace(monkeypatch):
    sid = "test_sanitized_payload"
    memory_ctx = _memory_ctx()
    memory_ctx["session"].session_id = sid
    book = _dummy_book()
    # Use the LLM parser contract even in this storage-focused test.
    from gp_assistant.llm import interpret as interpret_mod

    class DummyLLM:
        def available(self):
            return True, "ok"

        def chat(self, messages, json_mode=False, **kwargs):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "subject": "market",
                                    "request": "chat",
                                    "freshness": "active_run",
                                    "references": {},
                                    "constraints": {},
                                    "ambiguity": {"confidence": 0.9, "notes": [], "needs_clarification": False},
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

    monkeypatch.setattr(interpret_mod, "LLMClient", DummyLLM)
    frame = parse_concern(memory_ctx, book, "hello")
    plan = plan_evidence(frame)
    evidence = build_evidence_pack(frame, memory_ctx, book, plan)
    judgment = judge_chat()
    reply = ReplyBundle(
        session_id=sid,
        text="hello",
        kind="chat",
        message={"message_kind": "chat", "narrative_text": "hello"},
        right_panel={"tradeable": True},
        grounding_summary={
            "market_phase": "POSTCLOSE_PENDING",
            "daily_target_day": "2026-01-01",
            "pulse_slot_at": None,
            "repair_status": "ready",
            "decision_basis_labels": ["background"],
        },
        tool_trace={"frame": frame.model_dump(), "evidence_refs": evidence.evidence_refs},
    )
    commit_turn(sid, "hello", reply, judgment)

    session_payload = get_session_payload(sid)
    assistant_turn = next(turn for turn in session_payload["recent_turns"] if turn["role"] == "assistant")
    assert session_payload["recent_claims"] == []
    assert "tool_trace" not in assistant_turn["meta"]

    sanitized = sanitize_chat_payload({"tool_trace": {"x": 1}, "reply": "ok"})
    assert "tool_trace" not in sanitized
    assert sanitized["reply"] == "ok"
