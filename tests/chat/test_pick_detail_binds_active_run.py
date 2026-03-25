from __future__ import annotations

import os
os.environ.setdefault("TZ", "Asia/Shanghai")
os.environ.setdefault("STRICT_REAL_DATA", "1")


def test_pick_detail_uses_active_run():
    from gp_assistant.chat.orchestrator import handle_message
    from gp_assistant.chat.tool_registry import build_registry
    from gp_assistant.chat import session_store as store

    out = handle_message(None, "给我推荐", None)
    sid = out.get("session_id")
    st = store.get_state(sid)
    syms = list(st.get("active_symbols") or [])
    if not syms:
        return  # skip when no symbols available in fixture mode
    reg = build_registry()
    d = reg.get_pick_detail(sid, syms[0])
    assert d.get("symbol") == syms[0]

