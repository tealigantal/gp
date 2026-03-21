from __future__ import annotations

from typing import Any, Dict, List

from .contracts import make_order_intent


def build_order_intents_from_gated_artifact(art: Dict[str, Any]) -> List[Dict[str, Any]]:
    run_id = str(art.get("run_id") or art.get("as_of") or "")
    as_of = str(art.get("as_of") or run_id)
    out: List[Dict[str, Any]] = []
    items = art.get("items") or []
    for it in items:
        gd = (it.get("gating_decision") or {})
        decision = gd.get("decision", "allow")
        if decision == "blocked":
            continue
        # priority & sizing from gating
        base_pri = 1.0
        base_size = 1.0
        warns: List[str] = []
        if decision == "degraded":
            base_pri = 0.5
            base_size = 0.5
            warns.append("degraded_gating")
        # intent fields
        thesis = it.get("thesis") or it.get("strategy_label") or it.get("strategy")
        entry_hint = list(it.get("entry_zone") or []) if it.get("entry_zone") else None
        stop_hint = it.get("stop")
        invalidation = list(it.get("invalidation") or [])
        confidence = it.get("confidence")
        prov = {
            "artifact_version": art.get("artifact_version", "v2"),
            "symbol": it.get("symbol"),
            "strategy": it.get("strategy"),
        }
        intent = make_order_intent(
            run_id=run_id,
            as_of=as_of,
            symbol=str(it.get("symbol")),
            side="buy",
            decision_source="gated_recommendation",
            gating_decision=gd,
            priority=base_pri,
            thesis=thesis if isinstance(thesis, str) else None,
            entry_hint=entry_hint,
            stop_hint=stop_hint if isinstance(stop_hint, (int, float)) else None,
            invalidation=invalidation,
            confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
            sizing_hint=base_size,
            warnings=warns,
            provenance=prov,
        )
        out.append(intent)
    return out

