from __future__ import annotations

from typing import Any, Dict, List
from datetime import datetime, timezone
import uuid


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_intent_id() -> str:
    return f"intent-{uuid.uuid4().hex[:12]}"


def make_order_intent(
    *,
    run_id: str,
    as_of: str,
    symbol: str,
    side: str,
    decision_source: str,
    gating_decision: Dict[str, Any],
    priority: float,
    thesis: str | None,
    entry_hint: List[float] | None,
    stop_hint: float | None,
    invalidation: List[str] | None,
    confidence: float | None,
    sizing_hint: float | None,
    warnings: List[str] | None,
    provenance: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "intent_id": new_intent_id(),
        "run_id": run_id,
        "as_of": as_of,
        "symbol": symbol,
        "side": side,
        "decision_source": decision_source,
        "gating_decision": gating_decision,
        "priority": float(priority),
        "thesis": thesis,
        "entry_hint": entry_hint,
        "stop_hint": stop_hint,
        "invalidation": invalidation or [],
        "confidence": confidence,
        "sizing_hint": sizing_hint,
        "status": "proposed",
        "warnings": warnings or [],
        "metadata": {"created_at": _now_iso()},
        "provenance": provenance,
    }


def make_execution_event(*, intent_id: str, event_type: str, symbol: str, source_run_id: str, notes: str | None = None) -> Dict[str, Any]:
    return {
        "event_id": f"evt-{uuid.uuid4().hex[:12]}",
        "intent_id": intent_id,
        "event_type": event_type,
        "timestamp": _now_iso(),
        "symbol": symbol,
        "notes": notes,
        "source_run_id": source_run_id,
    }

