from __future__ import annotations

from src.gp_assistant.strategy.champion import choose_champion
from src.gp_assistant.strategy import library as strat_lib


def test_champion_prefers_fresh_setup(monkeypatch):
    # Two strategies with similar event stats, different freshness
    strategies = {
        "A": {
            "cv": {"win_rate_5d_mean": 0.55, "mean_return_5d_mean": 0.01, "drawdown_proxy_mean": 0.02},
            "event": {"win_rate_5": 0.6, "win_rate_10": 0.55, "mean_return_5": 0.01, "mean_return_10": 0.015, "mdd10_proxy": 0.02, "k": 15},
            "setup": {"age": 30, "count": 1},
        },
        "B": {
            "cv": {"win_rate_5d_mean": 0.55, "mean_return_5d_mean": 0.01, "drawdown_proxy_mean": 0.02},
            "event": {"win_rate_5": 0.6, "win_rate_10": 0.55, "mean_return_5": 0.01, "mean_return_10": 0.015, "mdd10_proxy": 0.02, "k": 15},
            "setup": {"age": 1, "count": 5},
        },
    }
    # Make both champion-eligible
    monkeypatch.setattr(strat_lib, "METADATA", {"A": {"champion_eligible": True, "direction": "long", "live_enabled": True},
                                                 "B": {"champion_eligible": True, "direction": "long", "live_enabled": True}}, raising=False)

    cand = {"symbol": "X", "strategies": strategies}
    champs = choose_champion([cand])
    ch = champs.get("X")
    assert ch is not None
    assert ch.get("strategy") == "B", "fresh setup should win"
    # Ensure transparency fields are present
    assert "setup_penalty" in ch
    assert "score_breakdown" in ch and isinstance(ch["score_breakdown"], dict)
    assert "reasons" in ch

