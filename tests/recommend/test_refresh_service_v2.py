from __future__ import annotations

import types
import pandas as pd
import numpy as np
from gp_assistant.recommend.refresh_service import refresh_symbols_v2
from src.gp_assistant.strategy import library as strat_lib
from gp_assistant.chat.refresh_service import refresh_symbols as chat_refresh


def test_refresh_symbols_v2_and_chat_compat(monkeypatch):
    # Provide a minimal strategy to ensure deterministic bands/diagnostics in v1
    Setup = types.SimpleNamespace
    def _detect(df):
        return [Setup(idx=len(df) - 1)]
    def _bands(df, s):
        lc = float(df["close"].iloc[-1])
        return {"S1": lc * 0.95, "S2": lc * 0.98, "R1": lc * 1.05, "R2": lc * 1.08}
    fake_mod = types.SimpleNamespace(detect_setups=_detect, key_bands=_bands)
    monkeypatch.setattr(strat_lib, "REGISTRY", {"F": fake_mod}, raising=False)

    # Stable market data
    n = 180
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    close = pd.Series(np.linspace(50, 60, n))
    df = pd.DataFrame({
        "date": dates,
        "open": close.values,
        "high": close.values,
        "low": close.values,
        "close": close.values,
        "volume": [1e7] * n,
        "amount": (close.values * 1.0) * 1e7,
    })
    from src.gp_assistant.recommend import datahub as dh
    def fake_daily(sym: str, as_of: str | None, min_len: int = 250, prefer_cache_only: bool = False):
        meta = {"len": len(df), "source": "fake", "insufficient_history": False}
        return df.copy(), meta
    monkeypatch.setattr(dh.MarketDataHub, "daily_ohlcv", fake_daily, raising=False)

    syms = ["600519"]
    v2 = refresh_symbols_v2(syms)
    assert v2.get("ok") is True
    assert isinstance(v2.get("items"), list) and len(v2["items"]) >= 1
    # chat layer still returns old picks for compatibility
    chat = chat_refresh(syms)
    assert chat.get("ok") is True
    assert isinstance(chat.get("picks"), list)
