from __future__ import annotations

import os
import types
import pandas as pd
from fastapi.testclient import TestClient

from gp_assistant.gateway.app import app
from src.gp_assistant.strategy import library as strat_lib


client = TestClient(app)


def test_server_compact_payload_keeps_new_fields(monkeypatch):
    os.environ.setdefault("STRICT_REAL_DATA", "0")

    # Minimal strategy to ensure champion and trade_plan are produced
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
    close = pd.Series(pd.linspace(50, 60, n))
    df = pd.DataFrame({
        "date": dates,
        "open": close.values,
        "high": close.values,
        "low": close.values,
        "close": close.values,
        "volume": [1e7] * n,
        "amount": (close.values * 1.0) * 1e7,
    })
    from src.gp_assistant.selection_engine import datahub as dh
    def fake_daily(sym: str, as_of: str | None, min_len: int = 250, prefer_cache_only: bool = False):
        meta = {"len": len(df), "source": "fake", "insufficient_history": False}
        return df.copy(), meta
    monkeypatch.setattr(dh.MarketDataHub, "daily_ohlcv", fake_daily, raising=False)

    # Call API
    body = {"topk": 1, "universe": "symbols", "symbols": ["600519"], "detail": "compact"}
    r = client.post("/api/recommend", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    picks = data.get("picks") or []
    assert len(picks) >= 1
    p0 = picks[0]
    assert "final_score" in p0
    assert "score_breakdown" in p0
    assert "champion" in p0 and "reasons" in (p0["champion"] or {})
    tp = (p0.get("trade_plan") or {})
    # new fields must be visible
    assert "execution_bands" in tp and isinstance(tp["execution_bands"], dict)
    assert "structural_bands" in tp and isinstance(tp["structural_bands"], dict)
    assert "diagnostics" in tp and isinstance(tp["diagnostics"], dict)
