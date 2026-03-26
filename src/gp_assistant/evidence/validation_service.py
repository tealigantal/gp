from __future__ import annotations

from typing import Any, Dict

from ..validation.event_stats import load_event_stats
from ..validation.walkforward_stats import load_walkforward
from ..validation.paper_trade import load_paperfolio
from ..validation.strategy_health import load_strategy_health


def build_validation_slice(strategy_id: str | None = None) -> Dict[str, Any]:
    if strategy_id:
        return {
            'event_stats': load_event_stats(strategy_id),
            'walkforward': load_walkforward(strategy_id),
            'paper_trade': load_paperfolio(),
            'strategy_health': load_strategy_health(strategy_id),
        }
    return {
        'paper_trade': load_paperfolio(),
    }
