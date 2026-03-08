from __future__ import annotations

from src.gp_assistant.strategy.champion import choose_champion
from src.gp_assistant.strategy import library as strat_lib


def test_champion_uses_per_strategy_event_not_pseudo(monkeypatch):
    # Prepare two strategies with identical CV but different event stats
    candidates = [
        {
            "symbol": "X1",
            "strategies": {
                "A": {"cv": {"win_rate_5d_mean": 0.55, "mean_return_5d_mean": 0.01, "drawdown_proxy_mean": -0.1},
                       "event": {"k": 20, "win_rate_5": 0.45, "win_rate_10": 0.46, "mean_return_5": 0.002, "mean_return_10": 0.003, "mdd10_proxy": -0.08}},
                "B": {"cv": {"win_rate_5d_mean": 0.55, "mean_return_5d_mean": 0.01, "drawdown_proxy_mean": -0.1},
                       "event": {"k": 20, "win_rate_5": 0.60, "win_rate_10": 0.58, "mean_return_5": 0.004, "mean_return_10": 0.006, "mdd10_proxy": -0.05}},
            },
        }
    ]
    # Ensure both are eligible in metadata
    meta = dict(getattr(strat_lib, "METADATA", {}))
    meta.update({"A": {"champion_eligible": True, "live_enabled": True, "direction": "long"},
                 "B": {"champion_eligible": True, "live_enabled": True, "direction": "long"}})
    monkeypatch.setattr(strat_lib, "METADATA", meta, raising=False)

    out = choose_champion(candidates)
    assert out["X1"]["strategy"] == "B", "Champion should prefer higher event performance when CV is same"

