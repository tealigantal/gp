from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..kernel.facade import (
    get_gated_artifact_v2,
    get_validation_summary,
    get_portfolio_state,
    get_execution_events,
    get_live_shadow_latest_summary,
    build_order_intents,
)
from .contracts import empty_workbench_snapshot


def get_workbench_snapshot(run_id: Optional[str] = None, as_of: Optional[str] = None, event_limit: int = 100) -> Dict[str, Any]:
    snap = empty_workbench_snapshot()
    warn: List[str] = []
    # recommend gated view
    try:
        rec = get_gated_artifact_v2(run_id=run_id, as_of=as_of)
        snap["recommend"] = rec
        snap["as_of"] = rec.get("as_of") or rec.get("run_id")
    except Exception:
        warn.append("recommend_unavailable")
        snap["recommend"] = {}
    # validation summary
    try:
        snap["validation_summary"] = get_validation_summary()
    except Exception:
        warn.append("validation_summary_unavailable")
        snap["validation_summary"] = {"parts": {}}
    # portfolio
    try:
        snap["portfolio"] = get_portfolio_state()
    except Exception:
        warn.append("portfolio_unavailable")
        snap["portfolio"] = {"positions": [], "pending_intents": [], "recent_events": []}
    # events
    try:
        snap["execution_events"] = get_execution_events(limit=event_limit)
    except Exception:
        warn.append("execution_events_unavailable")
        snap["execution_events"] = []
    # live shadow
    try:
        snap["live_shadow_summary"] = get_live_shadow_latest_summary()
    except Exception:
        warn.append("live_shadow_unavailable")
        snap["live_shadow_summary"] = {"available": False, "dates": []}
    # intents preview from current recommend (do not write to store)
    try:
        preview = build_order_intents(run_id=run_id, as_of=as_of)
        snap["intents_preview"] = preview
    except Exception:
        warn.append("intents_preview_unavailable")
        snap["intents_preview"] = []
    snap["warnings"] = warn
    snap["source_status"] = {"event_limit": event_limit}
    return snap

