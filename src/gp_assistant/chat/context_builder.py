from __future__ import annotations

from typing import Any, Dict, List

from . import session_store as store


def build_turn_context(session_id: str) -> Dict[str, Any]:
    sid = store.ensure_session(session_id)
    st = store.get_state(sid)

    # Best-effort recent bundle summaries (not heavy)
    # We persist latest right panel back to session state for lightweight retrieval.
    recent_bundles: List[Dict[str, Any]] = []
    try:
        rp = st.get("last_right_panel")
        if isinstance(rp, dict):
            recent_bundles.append({
                "active_run_id": rp.get("active_run_id"),
                "active_symbols": rp.get("active_symbols"),
                "tradeable": rp.get("tradeable"),
                "run_gating": rp.get("run_gating"),
            })
    except Exception:
        pass

    return {
        "session_state": {
            "active_run_id": st.get("active_run_id"),
            "previous_run_id": st.get("previous_run_id"),
            "focus_symbol": st.get("focused_symbol") or st.get("current_focus_symbol"),
            "active_symbols": st.get("active_symbols") or [],
        },
        "recent_bundles": recent_bundles,
    }

