from __future__ import annotations

from typing import Any, Dict, List
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_portfolio_state() -> Dict[str, Any]:
    return {
        "as_of": _now_iso(),
        "cash": None,
        "equity": None,
        "positions": [],
        "pending_intents": [],
        "recent_events": [],
        "realized_pnl": None,
        "unrealized_pnl": None,
        "exposure_summary": {},
        "warnings": [],
    }

