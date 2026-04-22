from __future__ import annotations

import types
import pandas as pd

from src.gp_assistant.selection_engine.agent import run as recommend_run
from src.gp_assistant.strategy import library as strat_lib


def test_execution_state_below_support_not_actionable(monkeypatch):
    # Fake strategy with bands such that S1 is above last_close (below support)
    Setup = types.SimpleNamespace
    def _detect(df):
        # pretend we have a very recent setup
        return [Setup(idx=len(df) - 2)]

    def _kb(df, s):
        # Use last close around 100; set S1=110 to force below_support
        lc = float(df["close"].iloc[-1])
        return {"S1": lc * 1.10, "S2": lc * 1.12, "R1": lc * 1.20, "R2": lc * 1.25}

    fake_mod = types.SimpleNamespace(
        detect_setups=_detect,
        key_bands=_kb,
        confirm_text=lambda s, q: {"window_A_text": "A", "window_B_text": "B"},
        invalidation=lambda s: ["X"],
    )
    monkeypatch.setattr(strat_lib, "REGISTRY", {"F": fake_mod}, raising=False)

    # Synthetic OHLCV
    n = 200
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    close = pd.Series(pd.linspace(80, 100, n))
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
    diag = tp.get("diagnostics") or {}
    state = str(diag.get("execution_state") or "")
    # Must not be actionable; should be below_support/breakdown_risk/observe_only
    assert state in {"below_support", "breakdown_risk", "observe_only"}
    assert bool(diag.get("actionable") is False)
    # Signed gap should retain direction info (negative)
    assert float(diag.get("signed_entry_gap_pct") or -1.0) < 0.0
    # Rerank penalty should be applied in score_breakdown
    sb = picks[0].get("score_breakdown") or {}
    assert "execution_state_penalty" in sb and float(sb["execution_state_penalty"]) < 0.0
