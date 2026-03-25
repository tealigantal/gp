from __future__ import annotations

"""
Run resolution service.

Responsibilities:
  - detect_cutoff(now) -> INTRADAY|EOD (delegate to recommend.run_policy)
  - is_run_valid(artifact, now) (delegate)
  - get_active_run(session_id, now, *, force_refresh=False, topk: int = 3)

This module centralizes time policy and run reuse/refresh so callers
do not duplicate staleness logic or mutate environment variables.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from ..kernel.facade import get_gated_artifact_v2 as _get_gated
from ..recommend.artifact_store import build_v2_dict_from_v1, persist_artifact_v2
from ..recommend.runner import run as recommend_run
from ..recommend.run_policy import detect_cutoff, is_artifact_valid
from . import session_store as store


def get_active_run(
    session_id: str,
    now: Optional[datetime] = None,
    *,
    force_refresh: bool = False,
    topk: int = 3,
) -> Dict[str, Any]:
    sid = store.ensure_session(session_id)
    st = store.get_state(sid)
    want_cut = detect_cutoff(now)

    # Try current active run if any
    art: Dict[str, Any] = {}
    rid = st.get("active_run_id")
    if rid and not force_refresh:
        try:
            base = _get_gated(run_id=rid)
            if isinstance(base, dict):
                art = base
        except Exception:
            art = {}

    valid = is_artifact_valid(art, now)

    if (not valid) or force_refresh:
        # Compute a fresh run deterministically; do not mutate env here
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

