from __future__ import annotations

from gp_assistant.chat import session_store as store
from gp_assistant.chat.orchestrator import handle_message


def test_rule_fallback_disabled_llm_path(monkeypatch):
    # Ensure LLM path disabled
    monkeypatch.delenv("GP_ENABLE_LLM_INTENT", raising=False)
    sid = store.ensure_session("t_rule_only")
    out = handle_message(sid, "第一名凭啥")
    assert isinstance(out.get("reply"), str)

