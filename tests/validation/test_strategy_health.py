from __future__ import annotations

from gp_assistant.validation.event_stats import save_event_stats
from gp_assistant.validation.walkforward_stats import save_walkforward
from gp_assistant.validation.strategy_health import compute_strategy_health


def test_strategy_health_states():
    # Healthy
    save_event_stats('S1', {"sample_size": 10, "d3_mean":0.01, "d5_mean":0.01, "d10_mean":0.02, "win_rate_d5":0.6})
    save_walkforward('S1', {"windows": [0.01, 0.02], "stable": True, "recent_rank": 1})
    h = compute_strategy_health('S1')
    assert h['status'] in {'healthy','warning','degraded','killed'}
    # Degraded
    save_event_stats('S2', {"sample_size": 10, "d3_mean":0.0, "d5_mean":0.0, "d10_mean":0.0, "win_rate_d5":0.4})
    save_walkforward('S2', {"windows": [-0.015], "stable": False, "recent_rank": 1})
    d = compute_strategy_health('S2')
    assert d['status'] in {'degraded','killed'}
    # Killed
    save_event_stats('S3', {"sample_size": 10, "d3_mean":-0.01, "d5_mean":-0.02, "d10_mean":-0.03, "win_rate_d5":0.2})
    save_walkforward('S3', {"windows": [-0.03], "stable": False, "recent_rank": 1})
    k = compute_strategy_health('S3')
    assert k['status'] == 'killed'
