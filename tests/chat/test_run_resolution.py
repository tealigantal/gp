from __future__ import annotations

import os
from datetime import datetime, timedelta

os.environ.setdefault("TZ", "Asia/Shanghai")
os.environ.setdefault("STRICT_REAL_DATA", "1")


def test_run_cutoff_detection_and_resolution():
    from gp_assistant.selection_engine.run_policy import detect_cutoff
    from gp_assistant.chat_compat.run_service import get_active_run
    from gp_assistant.chat_compat import session_store as store

    sid = store.ensure_session(None)
    # Before close -> INTRADAY
    dt = datetime.now()
    cut = detect_cutoff(dt)
    assert cut in {"INTRADAY", "EOD"}

    # First resolution should produce a run and bind to session
    out = get_active_run(sid, now=None, force_refresh=True, topk=3)
    assert out.get("active_run_id")
    st = store.get_state(sid)
    assert st.get("active_run_id") == out.get("active_run_id")
