from __future__ import annotations

import types
import pandas as pd

from src.gp_assistant.recommend.agent import run as recommend_run
from src.gp_assistant.strategy import library as strat_lib


def test_structural_bands_present_with_chip_fallback(monkeypatch):
    # Fake strategy without key_bands -> force chip fallback
    fake_mod = types.SimpleNamespace(
        detect_setups=lambda d: [],
        key_bands=lambda d, s: {},
    )
    monkeypatch.setattr(strat_lib, "REGISTRY", {"F": fake_mod}, raising=False)

    # Patch chip model to return stable bands around last_close
    from src.gp_assistant.strategy import chip_model as cm

    def fake_chip(feat: pd.DataFrame):
        # avg close ~ 10 -> returning 9/11 around cost 10
        return types.SimpleNamespace(band_90_low=9.0, band_90_high=11.0, avg_cost=10.0, dist_to_90_high_pct=0.5), {}

    monkeypatch.setattr(cm, "compute_chip", fake_chip, raising=False)

    # Synthetic OHLCV around 10
    n = 200
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    close = pd.Series([10.0] * n)
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

    payload = recommend_run(universe="symbols", symbols=["FAKE1"], topk=1)
    tp = (payload.get("picks") or [{}])[0].get("trade_plan") or {}

    # structural bands must be present and equal to execution bands (compat)
    sb = tp.get("structural_bands") or {}
    eb = tp.get("execution_bands") or tp.get("bands") or {}
    assert sb and eb
    assert float(sb.get("S1", 0.0)) == float(eb.get("S1", 0.0))
    assert tp.get("structural_band_source") == "chip_fallback"
    # execution source should be direct (no recenter fallback under equal bands)
    assert tp.get("execution_band_source") in {"direct", "chip_fallback"}
    diag = tp.get("diagnostics") or {}
    assert isinstance(diag, dict) and "band_source" in diag

