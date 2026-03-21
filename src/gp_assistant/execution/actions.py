from __future__ import annotations

from typing import Any, Dict, Optional

from .intent_builder import build_order_intents_from_gated_artifact
from ..kernel.facade import get_gated_artifact_v2
from ..portfolio.store import read_portfolio_state, save_portfolio_state, append_events
from .contracts import make_execution_event


def admit_intent(*, run_id: Optional[str], as_of: Optional[str], symbol: str, note: Optional[str] = None) -> Dict[str, Any]:
    art = get_gated_artifact_v2(run_id=run_id, as_of=as_of)
    # build preview intents and locate target symbol
    intents = build_order_intents_from_gated_artifact(art)
    target = None
    for it in intents:
        if str(it.get("symbol")) == str(symbol):
            target = it
            break
    if not target:
        return {"ok": False, "error": "INTENT_NOT_AVAILABLE"}
    # admit to portfolio
    pf = read_portfolio_state()
    target2 = dict(target)
    target2["status"] = "admitted"
    pf.setdefault("pending_intents", []).append(target2)
    save_portfolio_state(pf)
    evt = make_execution_event(intent_id=str(target2.get("intent_id")), event_type="admitted", symbol=str(symbol), source_run_id=str(target2.get("run_id")), notes=note or "operator_admit")
    append_events([evt])
    return {"ok": True, "intent_id": target2.get("intent_id")}


def reject_intent(*, run_id: Optional[str], as_of: Optional[str], symbol: str, note: Optional[str] = None) -> Dict[str, Any]:
    # do not store; just log rejection
    art = get_gated_artifact_v2(run_id=run_id, as_of=as_of)
    # find item existence
    has = any(str(it.get("symbol")) == str(symbol) for it in (art.get("items") or []))
    if not has:
        return {"ok": False, "error": "SYMBOL_NOT_FOUND"}
    # log event
    evt = make_execution_event(intent_id=f"manual-{symbol}", event_type="rejected", symbol=str(symbol), source_run_id=str(art.get("run_id")), notes=note or "operator_reject")
    append_events([evt])
    return {"ok": True}


def cancel_intent(*, intent_id: str, note: Optional[str] = None) -> Dict[str, Any]:
    pf = read_portfolio_state()
    pending = list(pf.get("pending_intents") or [])
    new_pending = []
    target = None
    for it in pending:
        if str(it.get("intent_id")) == str(intent_id):
            target = it
        else:
            new_pending.append(it)
    if not target:
        return {"ok": False, "error": "INTENT_NOT_FOUND"}
    pf["pending_intents"] = new_pending
    save_portfolio_state(pf)
    evt = make_execution_event(intent_id=str(intent_id), event_type="cancelled", symbol=str(target.get("symbol")), source_run_id=str(target.get("run_id")), notes=note or "operator_cancel")
    append_events([evt])
    return {"ok": True}

