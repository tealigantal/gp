from __future__ import annotations

from typing import Any, Dict, Iterable, List

from ..decision_engine.pipeline import run_market_memory_selection
from .outcome_tracker import track_decision_snapshot_outcomes


def run_agent_backtest(days: Iterable[str], *, topk: int = 3, risk_profile: str = "normal") -> Dict[str, Any]:
    """Backtest the full decision agent with time-travel-safe Market Memory.

    Each day routes through the same production pipeline. Retrieval only uses
    events with ``as_of < day`` and the signal builder only stores historical
    events whose forward outcome is knowable by that day.
    """

    rows: List[Dict[str, Any]] = []
    for day in days:
        result = run_market_memory_selection(date=str(day), topk=topk, risk_profile=risk_profile)
        snapshot_id = str(result.get("decision_context_snapshot_id") or "")
        outcome = track_decision_snapshot_outcomes(snapshot_id) if snapshot_id else {"ok": False, "reason": "snapshot_missing"}
        rows.append(
            {
                "day": str(day),
                "decision": result.get("decision"),
                "tradeable": result.get("tradeable"),
                "snapshot_id": snapshot_id,
                "top_symbols": [item.get("symbol") for item in (result.get("picks") or [])],
                "outcome": outcome,
            }
        )
    no_trade_rows = [row for row in rows if row.get("decision") == "no_trade"]
    trade_rows = [row for row in rows if row.get("decision") == "recommend"]
    return {
        "schema": "AgentBacktest.v1",
        "sample_days": len(rows),
        "recommend_days": len(trade_rows),
        "no_trade_days": len(no_trade_rows),
        "rows": rows,
        "time_travel_policy": {
            "market_data": "as_of_day_only",
            "market_memory": "events_as_of_before_day_only",
            "outcomes": "tracked_after_snapshot",
        },
    }
