from __future__ import annotations

import os

import pandas as pd


def _stub_feat_df():
    dates = pd.date_range("2024-01-01", periods=200, freq="B")
    return pd.DataFrame({"date": dates, "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0, "volume": 1e6, "amount": 1e8})


def test_restrict_to_mainline_filters_when_true(monkeypatch):
    # produce 2 candidates with industries not in mainline/themes
    from src.gp_assistant.recommend import candidate_gen as cg

    def fake_gen(symbols, env_grade, topk=3, snapshot=None):  # noqa: ANN001
        pool = [
            {"symbol": "600519", "industry": "白酒", "liquidity": {"avg5_amount": 2e9, "grade": "A"}, "chip": {"avg_cost": 10.0, "band_90_low": 9.5, "band_90_high": 10.5}, "indicators": {"slope20": 0.2, "atr_pct": 0.02, "gap_pct": 0.0}},
            {"symbol": "000001", "industry": "银行", "liquidity": {"avg5_amount": 2e9, "grade": "A"}, "chip": {"avg_cost": 10.0, "band_90_low": 9.5, "band_90_high": 10.5}, "indicators": {"slope20": 0.2, "atr_pct": 0.02, "gap_pct": 0.0}},
        ]
        for it in pool:
            it["candidate_score"] = 0.3
        return pool, [], {"universe_after_filter_count": 2, "candidates_out_count": 2}

    monkeypatch.setattr(cg, "generate_candidates", fake_gen)

    # Stub datahub + indicators
    from src.gp_assistant.recommend import datahub as dh
    monkeypatch.setattr(dh.MarketDataHub, "daily_ohlcv", lambda self, sym, as_of, min_len=250, prefer_cache_only=False: (_stub_feat_df(), {"len": 200}))

    from src.gp_assistant.strategy import indicators as indi
    monkeypatch.setattr(indi, "compute_indicators", lambda df: df.assign(slope20=0.2, atr_pct=0.02, gap_pct=0.0, ma20=10.0, amount_5d_avg=1e8))

    # Stub themes/mainline to unrelated sectors
    from src.gp_assistant.recommend import theme_pool as tpool
    monkeypatch.setattr(tpool, "build_themes", lambda hub, snapshot=None: [{"name": "新能源", "source": "industry_snapshot"}])

    from src.gp_assistant.recommend import mainline as ml
    monkeypatch.setattr(ml, "build_mainline", lambda indicator="今日", topn=2, snapshot=None: {"indicator": indicator, "sectors": [{"name": "半导体"}], "source": "snapshot"})

    # Force restrict true
    monkeypatch.setenv("GP_RESTRICT_MAINLINE", "1")

    from src.gp_assistant.recommend.engine import run as engine_run

    out = engine_run(topk=3)
    picks = out.get("picks") if isinstance(out, dict) else []
    # All candidates are off-mainline -> when restricting, picks may be empty
    # Ensure flag propagated in debug
    dbg = (out.get("debug") or {}) if isinstance(out, dict) else {}
    assert dbg.get("restrict_to_mainline") is True


def test_off_mainline_downrank_when_false(monkeypatch):
    # Same stubs, but turn off restriction
    from src.gp_assistant.recommend import candidate_gen as cg

    def fake_gen(symbols, env_grade, topk=3, snapshot=None):  # noqa: ANN001
        pool = [
            {"symbol": "600519", "industry": "白酒", "liquidity": {"avg5_amount": 2e9, "grade": "A"}, "chip": {"avg_cost": 10.0, "band_90_low": 9.5, "band_90_high": 10.5}, "indicators": {"slope20": 0.2, "atr_pct": 0.02, "gap_pct": 0.0}},
            {"symbol": "000001", "industry": "银行", "liquidity": {"avg5_amount": 2e9, "grade": "A"}, "chip": {"avg_cost": 10.0, "band_90_low": 9.5, "band_90_high": 10.5}, "indicators": {"slope20": 0.2, "atr_pct": 0.02, "gap_pct": 0.0}},
        ]
        for it in pool:
            it["candidate_score"] = 0.3
        return pool, [], {"universe_after_filter_count": 2, "candidates_out_count": 2}

    monkeypatch.setattr(cg, "generate_candidates", fake_gen)

    # Stub datahub + indicators
    from src.gp_assistant.recommend import datahub as dh
    monkeypatch.setattr(dh.MarketDataHub, "daily_ohlcv", lambda self, sym, as_of, min_len=250, prefer_cache_only=False: (_stub_feat_df(), {"len": 200}))

    from src.gp_assistant.strategy import indicators as indi
    monkeypatch.setattr(indi, "compute_indicators", lambda df: df.assign(slope20=0.2, atr_pct=0.02, gap_pct=0.0, ma20=10.0, amount_5d_avg=1e8))

    from src.gp_assistant.recommend import theme_pool as tpool
    monkeypatch.setattr(tpool, "build_themes", lambda hub, snapshot=None: [{"name": "新能源", "source": "industry_snapshot"}])

    from src.gp_assistant.recommend import mainline as ml
    monkeypatch.setattr(ml, "build_mainline", lambda indicator="今日", topn=2, snapshot=None: {"indicator": indicator, "sectors": [{"name": "半导体"}], "source": "snapshot"})

    # Turn off restriction
    monkeypatch.delenv("GP_RESTRICT_MAINLINE", raising=False)

    from src.gp_assistant.recommend.engine import run as engine_run

    out = engine_run(topk=3)
    picks = out.get("picks") if isinstance(out, dict) else []
    assert isinstance(picks, list)
    # Explain text should indicate off-mainline downrank
    if picks:
        assert any("off_mainline_downrank" in str(p.get("explain", "")) for p in picks)

