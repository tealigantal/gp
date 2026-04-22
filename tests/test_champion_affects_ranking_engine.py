from __future__ import annotations

import types

import pandas as pd


def _stub_feat_df():
    dates = pd.date_range("2024-01-01", periods=260, freq="B")
    df = pd.DataFrame({
        "date": dates,
        "open": 10.0,
        "high": 10.5,
        "low": 9.5,
        "close": 10.0,
        "volume": 1e6,
        "amount": 1e8,
    })
    return df


def test_champion_score_changes_order(monkeypatch):
    # Monkeypatch candidate_gen to provide two candidates with similar base score
    from src.gp_assistant.selection_engine import candidate_gen as cg

    def fake_gen(symbols, env_grade, topk=3, snapshot=None):  # noqa: ANN001
        pool = [
            {"symbol": "600519", "industry": "闁谎傜矙閸?, "liquidity": {"avg5_amount": 2e9, "grade": "A"}, "chip": {"avg_cost": 10.0, "band_90_low": 9.5, "band_90_high": 10.5}, "indicators": {"slope20": 0.5, "atr_pct": 0.02, "gap_pct": 0.0}},
            {"symbol": "000001", "industry": "闂佺偓鍎奸、?, "liquidity": {"avg5_amount": 2e9, "grade": "A"}, "chip": {"avg_cost": 10.0, "band_90_low": 9.5, "band_90_high": 10.5}, "indicators": {"slope20": 0.5, "atr_pct": 0.02, "gap_pct": 0.0}},
        ]
        for it in pool:
            it["candidate_score"] = 0.5
        return pool, [], {"universe_after_filter_count": 2, "candidates_out_count": 2}

    monkeypatch.setattr(cg, "generate_candidates", fake_gen)

    # Monkeypatch datahub + indicators to avoid heavy deps
    from src.gp_assistant.selection_engine import datahub as dh
    monkeypatch.setattr(dh.MarketDataHub, "daily_ohlcv", lambda self, sym, as_of, min_len=250, prefer_cache_only=False: (_stub_feat_df(), {"len": 260}))

    from src.gp_assistant.strategy import indicators as indi
    monkeypatch.setattr(indi, "compute_indicators", lambda df: df.assign(slope20=0.5, atr_pct=0.02, gap_pct=0.0, ma20=10.0, amount_5d_avg=1e8))

    # Champion chooser: make 600519 higher score
    from src.gp_assistant.strategy import champion as champ

    def fake_choose(pool):  # noqa: ANN001
        return {"600519": {"strategy": "S1", "score": 1.0, "setup_penalty": 0.0, "reasons": []}, "000001": {"strategy": "S1", "score": 0.1, "setup_penalty": 0.0, "reasons": []}}

    monkeypatch.setattr(champ, "choose_champion", fake_choose)

    # Run engine
    from src.gp_assistant.selection_engine.engine import run as engine_run

    out = engine_run(topk=2)
    picks = out.get("picks") if isinstance(out, dict) else []
    assert len(picks) == 2
    # 600519 should be first due to higher champion score
    assert str(picks[0].get("symbol")) in {"600519", "sh600519"}
    assert picks[0].get("score_breakdown", {}).get("champion_component", 0.0) >= picks[1].get("score_breakdown", {}).get("champion_component", 0.0)
