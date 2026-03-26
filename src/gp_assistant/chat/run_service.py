from __future__ import annotations

"""
Run resolution service.

Resolves two distinct flows:
  - resolve_active_run(...): mainline run for recommend/refresh flows; may trigger new run
  - resolve_referenced_run(...): follow-up flows; binds to referenced_run_id first and never auto-recompute

Also exposes thin wrappers for legacy imports: get_active_run -> resolve_active_run.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from ..kernel.facade import get_gated_artifact_v2 as _get_gated
from ..recommend.artifact_store import build_v2_dict_from_v1, persist_artifact_v2
from ..recommend.runner import run as recommend_run
from ..recommend.trading_clock import is_run_valid_for_operation
from . import session_store as store

def resolve_active_run(
    session_id: str,
    now: Optional[datetime] = None,
    *,
    force_refresh: bool = False,
    topk: int = 3,
) -> Dict[str, Any]:
    sid = store.ensure_session(session_id)
    st = store.get_state(sid)

    # Try to reuse current active run when valid for recommendation
    art: Dict[str, Any] = {}
    rid = st.get("active_run_id")
    if rid and not force_refresh:
        try:
            base = _get_gated(run_id=rid)
            if isinstance(base, dict):
                art = base
        except Exception:
            art = {}

    valid = is_run_valid_for_operation(art, now, operation="recommend") if art else False

    if (not valid) or force_refresh:
        # Compute a fresh run deterministically
        v1 = recommend_run(mode="default", date=None, topk=topk or 3, universe="auto", symbols=None, risk_profile="normal")
        v2 = build_v2_dict_from_v1(v1)
        rid2 = str(v2.get("run_id") or v2.get("as_of") or "")
        if rid2:
            try:
                persist_artifact_v2(rid2, v2)
            except Exception:
                pass
            art = _get_gated(run_id=rid2)
            # Update session run context
            items = art.get("items") or []
            symbols = [str((it or {}).get("symbol") or "") for it in items if isinstance(it, dict) and (it or {}).get("symbol")]
            try:
                # migrate previous then set active
                st0 = store.get_state(sid)
                prev_run = st0.get("active_run_id")
                prev_syms = st0.get("active_symbols") or []
                store.update_state(sid, {"previous_run_id": prev_run, "previous_active_symbols": list(prev_syms or [])})
                store.update_state(sid, {"active_run_id": art.get("run_id"), "active_symbols": list(symbols)})
            except Exception:
                pass
            return {
                "active_run_id": art.get("run_id"),
                "tradeable": art.get("tradeable"),
                "run_gating": art.get("run_gating"),
                "reason": art.get("reason"),
                "items": art.get("items") or [],
                "as_of": art.get("as_of"),
                "reused_run": False,
                "stale": False,
                "refresh_reason": "force_refresh" if force_refresh else ("invalid_previous_run"),
            }

    # Valid current artifact; ensure session context aligned and report reuse
    try:
        items = art.get("items") or []
        symbols = [str((it or {}).get("symbol") or "") for it in items if isinstance(it, dict) and (it or {}).get("symbol")]
        store.update_state(sid, {"active_run_id": art.get("run_id"), "active_symbols": list(symbols)})
    except Exception:
        pass
    return {
        "active_run_id": art.get("run_id"),
        "tradeable": art.get("tradeable"),
        "run_gating": art.get("run_gating"),
        "reason": art.get("reason"),
        "items": art.get("items") or [],
        "as_of": art.get("as_of"),
        "reused_run": True,
        "stale": False,
        "refresh_reason": None,
    }


def resolve_referenced_run(session_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Resolve run for follow-up flows without auto-refresh.

    Priority: referenced_run_id -> active_run_id. Never triggers recomputation.
    """
    sid = store.ensure_session(session_id)
    st = store.get_state(sid)
    rid = st.get("referenced_run_id") or st.get("active_run_id")
    if not rid:
        raise FileNotFoundError("NO_REFERENCED_OR_ACTIVE_RUN")
    art = _get_gated(run_id=rid)
    return {
        "resolved_run_id": art.get("run_id"),
        "tradeable": art.get("tradeable"),
        "run_gating": art.get("run_gating"),
        "reason": art.get("reason"),
        "items": art.get("items") or [],
        "as_of": art.get("as_of"),
        "reused_run": True,
        "stale": False,
        "refresh_reason": None,
    }


# Backward alias
def get_active_run(session_id: str, now: Optional[datetime] = None, *, force_refresh: bool = False, topk: int = 3) -> Dict[str, Any]:
    return resolve_active_run(session_id, now, force_refresh=force_refresh, topk=topk)
