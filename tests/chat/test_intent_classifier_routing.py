from __future__ import annotations

import os
from typing import Dict, Any

from gp_assistant.chat import session_store as store
from gp_assistant.chat.orchestrator import handle_message


class _MockIC:
    def __init__(self, intent: str, symbol=None, symbols=None, ordinal=None, confidence=0.95):
        self.intent = intent
        self.symbol = symbol
        self.symbols = symbols or []
        self.ordinal = ordinal
        self.query_rewrite = None
        self.confidence = confidence
        self.reason = "mock"


def _mock_classifier(session_id: str, message: str):  # noqa: ANN001
    s = message.strip()
    if s in {"今天是不是不太适合做", "为什么今天不做"}:
        return _MockIC("ask_no_trade_reason")
    if s in {"第一名凭啥", "第二个差在哪"}:
        return _MockIC("ranking_explain")
    if s in {"要不要减仓"}:
        return _MockIC("exit_decision")
    if s in {"研究一下 600519", "研究一下600519"}:
        return _MockIC("analyze_symbol", symbol="600519")
    if s in {"对比前两只"}:
        return _MockIC("compare_symbols", ordinal=2)
    if s in {"rr 是什么意思", "RR 是什么意思"}:
        return _MockIC("general_explain")
    if s in {"重新推荐", "刷新一下", "再算一遍"}:
        return _MockIC("refresh_recommend")
    return _MockIC("unknown", confidence=0.3)


def test_classifier_routing_basic(monkeypatch):
    # Enable LLM intent path and patch classifier
    monkeypatch.setenv("GP_ENABLE_LLM_INTENT", "1")
    import gp_assistant.chat.intent_classifier as ic_mod

    monkeypatch.setattr(ic_mod, "classify_intent_llm", _mock_classifier)

    sid = store.ensure_session("t_cls_route")
    store.update_state(sid, {"active_symbols": ["AAA", "BBB", "CCC"]})
    store.set_focus(sid, "600519")

    cases = [
        ("今天是不是不太适合做", "ask_no_trade_reason"),
        ("第一名凭啥", "ranking_explain"),
        ("第二个差在哪", "ranking_explain"),
        ("要不要减仓", "exit_decision"),
        ("研究一下 600519", "analyze_symbol"),
        ("对比前两只", "compare_symbols"),
        ("rr 是什么意思", "general_explain"),
        ("重新推荐", "refresh_trade_plan"),
    ]

    for msg, expect in cases:
        out = handle_message(sid, msg)
        meta: Dict[str, Any] = (out.get("tool_trace") or {}).get("intent_debug") or {}
        assert meta.get("final_intent") == expect, f"{msg}: {meta}"

