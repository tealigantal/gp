from __future__ import annotations

import os
os.environ.setdefault("TZ", "Asia/Shanghai")
os.environ.setdefault("STRICT_REAL_DATA", "1")


def test_orchestrator_basic_flow():
    from gp_assistant.chat_compat.orchestrator import handle_message

    out = handle_message(None, "缂佹瑦鍨滈幒銊ㄥ礃3閸?, None)
    assert isinstance(out, dict)
    assert out.get("session_id")
    assert isinstance(out.get("reply"), str)
    rp = out.get("right_panel") or {}
    assert "active_run_id" in rp
    assert isinstance(rp.get("active_symbols"), list)
