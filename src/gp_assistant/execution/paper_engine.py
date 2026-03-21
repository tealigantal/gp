from __future__ import annotations

from typing import Any, Dict, List

from .contracts import make_execution_event
from ..portfolio.store import read_portfolio_state, save_portfolio_state, append_events


def run_paper_execution(intents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Minimal paper/shadow execution engine.

    - admit provided intents (status -> admitted)
    - append to portfolio.pending_intents
    - write execution events
    - return summary
    """
    state = read_portfolio_state()
    admitted: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    for it in (intents or []):
        it2 = dict(it)
        it2["status"] = "admitted"
        admitted.append(it2)
        events.append(
            make_execution_event(
                intent_id=str(it2.get("intent_id")),
                event_type="admitted",
                symbol=str(it2.get("symbol")),
                source_run_id=str(it2.get("run_id")),
                notes="paper_admit",
            )
        )
    # Update portfolio state
    pending = list(state.get("pending_intents") or [])
    pending.extend(admitted)
    state["pending_intents"] = pending
    save_portfolio_state(state)
    append_events(events)
    return {"ok": True, "admitted": len(admitted), "events": len(events)}

