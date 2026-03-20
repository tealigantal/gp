import os
os.environ.setdefault("STRICT_REAL_DATA", "0")
os.environ.setdefault("TZ", "Asia/Shanghai")

from typing import Any, Dict, List
from fastapi.testclient import TestClient

from gp_assistant.server.app import app


client = TestClient(app)


def _start_chat(message: str, session_id: str | None = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"message": message}
    if session_id:
        body["session_id"] = session_id
    r = client.post("/api/chat", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _thread_items(cid: str) -> List[Dict[str, Any]]:
    r = client.get(f"/api/threads/{cid}/items")
    assert r.status_code == 200, r.text
    return r.json()


def _last_bundle(cid: str) -> Dict[str, Any]:
    items = _thread_items(cid)
    for it in reversed(items):
        if it.get("kind") == "assistant_bundle":
            return it.get("bundle") or {}
    raise AssertionError("no assistant_bundle in thread")


def test_tool_calling_finance_agent_requires_tool_results_for_finance_answers():
    j1 = _start_chat("给我推荐3只")
    cid = j1.get("session_id")
    b = _last_bundle(cid)
    assert isinstance(b.get("tool_results"), list)
    assert len(b.get("tool_results")) > 0


def test_explain_selection_set_never_fabricates_symbols():
    j1 = _start_chat("生成推荐")
    cid = j1.get("session_id")
    j2 = _start_chat("为什么选这三支呀", session_id=cid)
    b = _last_bundle(cid)
    g = b.get("grounding") or {}
    active = set([str(s) for s in (g.get("active_symbols") or [])])
    used = set([str(s) for s in (g.get("used_symbols") or [])])
    # used symbols are within active set (or empty)
    assert used.issubset(active)


def test_no_trade_bundle_never_contains_buy_semantics():
    j1 = _start_chat("给我推荐3只")
    cid = j1.get("session_id")
    b = _last_bundle(cid)
    g = b.get("grounding") or {}
    if g.get("tradeable") is False or ((g.get("run_gating") or {}).get("decision") not in (None, "allow")):
        txt = (b.get("text") or "").lower()
        assert ("buy" not in txt) and ("买入" not in txt) and ("建仓" not in txt)


def test_focus_symbol_updates_session_and_next_turn_grounds_correctly():
    j1 = _start_chat("给我推荐3只")
    cid = j1.get("session_id")
    # set focus to second symbol if available; else skip
    b = _last_bundle(cid)
    syms = (b.get("grounding") or {}).get("active_symbols") or []
    if len(syms) >= 2:
        focus = syms[1]
        r = client.post("/api/chat/focus", json={"session_id": cid, "focus_symbol": focus})
        assert r.status_code == 200
        _ = _start_chat("这只还能买吗", session_id=cid)
        b2 = _last_bundle(cid)
        cards = b2.get("cards") or []
        # pick_detail or exit_decision card should mention the focused symbol
        found = False
        for c in cards:
            if c.get("symbol") == focus:
                found = True; break
        assert found


def test_thread_api_returns_only_user_and_assistant_bundle():
    j1 = _start_chat("测试线程")
    cid = j1.get("session_id")
    its = _thread_items(cid)
    for it in its:
        if it.get("role") == "assistant":
            assert it.get("kind") == "assistant_bundle"


def test_legacy_financial_messages_are_archived_and_hidden():
    # Archive script should be callable and not crash; returns ok
    from gp_assistant.chat.archive_legacy_threads import archive_legacy_items
    out = archive_legacy_items()
    assert out.get("ok") is True


def test_agent_uses_tool_results_not_free_text_for_finance_followup():
    j1 = _start_chat("给我推荐3只")
    cid = j1.get("session_id")
    _ = _start_chat("为什么选这三支呀", session_id=cid)
    b = _last_bundle(cid)
    tools = [str((t or {}).get("tool")) for t in (b.get("tool_results") or [])]
    assert "ensure_recommendation" in tools
    assert "explain_selection_set" in tools or "get_pick_detail" in tools

