from __future__ import annotations

from typing import Any, Dict

from ..portfolio.store import read_portfolio_state, read_recent_events


def load_portfolio_snapshot() -> Dict[str, Any]:
    state = read_portfolio_state()
    state['recent_events'] = read_recent_events(limit=20)
    return state
