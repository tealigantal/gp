from __future__ import annotations

from typing import Any, Dict

from . import session_store
from .orchestrator import handle_message


def get_active_run(session_id: str, now: Any = None, force_refresh: bool = False, topk: int = 3) -> Dict[str, Any]:
    sid = session_store.ensure_session(session_id)
    state = session_store.get_state(sid)
    active_run_id = state.get("active_run_id")
    if force_refresh or not active_run_id:
        out = handle_message(sid, f"recommend {topk} picks")
        panel = out.get("right_panel") or {}
        active_run_id = panel.get("active_run_id") or out.get("run_id")
    return {"active_run_id": active_run_id}


def resolve_referenced_run(session_id: str) -> Dict[str, Any]:
    state = session_store.get_state(session_id)
    resolved = state.get("referenced_run_id") or state.get("active_run_id")
    return {"resolved_run_id": resolved}
