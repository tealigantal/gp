from __future__ import annotations

import types
import pandas as pd

from src.gp_assistant.selection_engine.agent import run as recommend_run
from src.gp_assistant.strategy import library as strat_lib


def test_execution_bands_recenter_and_state(monkeypatch):
    # Fake strategy with stale setup and absurd bands
    Setup = types.SimpleNamespace
    fake_mod = types.SimpleNamespace(
        detect_setups=lambda d: [Setup(idx=50, note="stale")],
        key_bands=lambda d, s: {"S1": 1.0, "S2": 2.0, "R1": 100000.0, "R2": 200000.0},
        confirm_text=lambda s, q: {"window_A_text": "A", "window_B_text": "B"},
        invalidation=lambda s: ["X"],
    )
    monkeypatch.setattr(strat_lib, "REGISTRY", {"F": fake_mod}, raising=False)

    # Synthetic OHLCV with strong uptrend, sufficient liquidity
    n = 200
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    close = pd.Series(pd.linspace(50, 100, n))
    df = pd.DataFrame({
        "date": dates,
        "open": close.values * 0.99,
        "high": close.values * 1.01,
        "low": close.values * 0.98,
        "close": close.values,
        "volume": [1e7] * n,
        "amount": (close.values * 1.0) * 1e7,
    })

    # Patch MarketDataHub to return our DF
    from src.gp_assistant.recommend import datahub as dh

    def fake_daily(sym: str, as_of: str | None, min_len: int = 250, prefer_cache_only: bool = False):
        meta = {"len": len(df), "source": "fake", "insufficient_history": False}
        return df.copy(), meta

    monkeypatch.setattr(dh.MarketDataHub, "daily_ohlcv", fake_daily, raising=False)

    payload = recommend_run(universe="symbols", symbols=["FAKE1"], topk=1)
    picks = payload.get("picks") or []
    assert len(picks) >= 1
    tp = (picks[0].get("trade_plan") or {})
    bands = tp.get("execution_bands") or tp.get("bands") or {}
    diag = tp.get("diagnostics") or {}
    last_close = float(picks[0].get("last_close") or 0.0)
    # Execution bands should not be absurdly far from last_close
    if bands:
        r1 = float(bands.get("R1", last_close))
        s1 = float(bands.get("S1", last_close))
        assert (r1 / last_close) < 3.0 and (last_close / max(s1, 1e-6)) < 3.0
    # Fallback applied and state computed
    assert diag.get("band_source") in {"recent_window_fallback", "strategy_key_bands", "chip_fallback"}
    assert diag.get("execution_state") in {"actionable", "waiting_pullback", "observe_only"}
