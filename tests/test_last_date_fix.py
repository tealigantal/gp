from __future__ import annotations

import pandas as pd

from src.gp_assistant.selection_engine.agent import run as recommend_run
from src.gp_assistant.strategy import library as strat_lib


def test_last_date_prefers_date_column(monkeypatch):
    # Use a minimal strategy to keep pipeline intact
    fake_mods = strat_lib.REGISTRY.copy()
    monkeypatch.setattr(strat_lib, "REGISTRY", fake_mods, raising=False)

    # Build deterministic daily data with proper date column
    dates = pd.date_range("2025-01-01", periods=90, freq="B")
    close = pd.Series(pd.linspace(10, 20, len(dates)))
    df = pd.DataFrame({
        "date": dates,
        "open": close.values * 0.99,
        "high": close.values * 1.01,
        "low": close.values * 0.98,
        "close": close.values,
        "volume": [1e6] * len(dates),
        "amount": (close.values * 1.0) * 1e6,
    })

    from src.gp_assistant.recommend import datahub as dh

    def fake_daily(sym: str, as_of: str | None, min_len: int = 250, prefer_cache_only: bool = False):
        meta = {"len": len(df), "source": "fake", "insufficient_history": False}
        return df.copy(), meta

    monkeypatch.setattr(dh.MarketDataHub, "daily_ohlcv", fake_daily, raising=False)

    out = recommend_run(universe="symbols", symbols=["ZZ0001"], topk=1)
    picks = out.get("picks") or []
    assert len(picks) >= 1
    ld = picks[0].get("last_date")
    # Should format to YYYY-MM-DD (not bare integer index)
    assert isinstance(ld, str) and len(ld) >= 8 and ld[:4].isdigit(), f"unexpected last_date: {ld}"
