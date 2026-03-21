from __future__ import annotations

from gp_assistant.validation.event_stats import save_event_stats
from gp_assistant.validation.walkforward_stats import save_walkforward
from gp_assistant.validation.strategy_health import compute_strategy_health, save_strategy_health


def test_lifecycle_save_and_use():
    save_event_stats('S4', {"sample_size": 5, "d3_mean":0.0, "d5_mean":0.01, "d10_mean":0.02, "win_rate_d5":0.5})
    save_walkforward('S4', {"windows": [0.0, 0.01, 0.02], "stable": True, "recent_rank": 1})
    obj = compute_strategy_health('S4')
    save_strategy_health('S4', obj)
    assert isinstance(obj, dict) and 'status' in obj
