from __future__ import annotations

from gp_assistant.validation.event_stats import compute_event_stats, save_event_stats, load_event_stats


def test_event_stats_roundtrip():
    stats = compute_event_stats([0.01, -0.02, 0.03], [0.02, 0.01, -0.01], [0.05, 0.0, -0.02])
    assert 'sample_size' in stats and 'd3_mean' in stats and 'win_rate_d5' in stats
    save_event_stats('sX', stats)
    got = load_event_stats('sX')
    assert got.get('available') is True
