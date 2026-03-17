from __future__ import annotations

from gp_assistant.validation.walkforward_stats import compute_walkforward_summary, save_walkforward, load_walkforward


def test_walkforward_roundtrip():
    series = [0.01]*10 + [-0.005]*10 + [0.02]*10
    wf = compute_walkforward_summary(series, window=10, recent_k=3)
    assert 'windows' in wf and isinstance(wf['windows'], list)
    save_walkforward('sX', wf)
    got = load_walkforward('sX')
    assert got.get('available') is True
