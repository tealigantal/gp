from __future__ import annotations

import os

from gp_assistant.chat import session_store as store
from gp_assistant.chat.orchestrator import handle_message


class _MockIC:
    def __init__(self):
        self.intent = "general_explain"
        self.symbol = None
        self.symbols = []
        self.ordinal = None
        self.query_rewrite = None
        self.confidence = 0.95
        self.reason = "mock"


def _mock_classifier(session_id: str, message: str):  # noqa: ANN001
    return _MockIC()


def test_general_explain_guard_redirects_trading(monkeypatch):
    # Enable LLM path, patch classifier to force general_explain
    monkeypatch.setenv("GP_ENABLE_LLM_INTENT", "1")
    import gp_assistant.chat.intent_classifier as ic_mod

    monkeypatch.setattr(ic_mod, "classify_intent_llm", _mock_classifier)

    sid = store.ensure_session("t_guard")
    out = handle_message(sid, "这只可以买么")
    meta = (out.get("tool_trace") or {}).get("intent_debug") or {}
    assert meta.get("final_intent") != "general_explain"

