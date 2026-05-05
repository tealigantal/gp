from __future__ import annotations

import pandas as pd


def _feat_df() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=200, freq="B")
    close = pd.Series(10.0 + (pd.RangeIndex(len(dates)) * 0.02))
    return pd.DataFrame(
        {
            "date": dates,
            "open": close.values,
            "high": close.values * 1.01,
            "low": close.values * 0.99,
            "close": close.values,
            "volume": 1e6,
            "amount": close.values * 1e6,
            "slope20": 0.2,
            "atr_pct": 0.02,
            "gap_pct": 0.0,
            "ma20": close.values,
            "amount_5d_avg": 1e8,
        }
    )


def test_mainline_missing_is_not_a_hard_filter(monkeypatch):
    from src.gp_assistant.selection_engine import agent
    from src.gp_assistant.selection_engine.engine import run as engine_run

    feat = _feat_df()

    def fake_gen(symbols, env_grade, topk=3, snapshot=None, **kwargs):  # noqa: ANN001
        pool = [
            {"symbol": "600519", "industry": "beverage", "candidate_score": 0.65, "chip": {"avg_cost": 10.2, "band_90_low": 9.8, "band_90_high": 10.6}, "indicators": {"slope20": 0.2, "atr_pct": 0.02, "gap_pct": 0.0}},
            {"symbol": "000001", "industry": "bank", "candidate_score": 0.55, "chip": {"avg_cost": 9.9, "band_90_low": 9.5, "band_90_high": 10.4}, "indicators": {"slope20": 0.2, "atr_pct": 0.02, "gap_pct": 0.0}},
        ]
        stats = {"universe_after_filter_count": 2, "candidates_out_count": 2}
        feats = {"600519": feat.copy(), "000001": feat.copy()}
        return pool, [], stats, feats

    monkeypatch.setattr(agent, "generate_candidates", fake_gen)
    monkeypatch.setattr(agent, "score_regime", lambda hub, snapshot=None: {"grade": "B"})
    monkeypatch.setattr(agent, "build_mainline", lambda indicator="today", topn=2, snapshot=None, candidates=None: {"indicator": indicator, "sectors": [], "errors": ["missing"], "source": "derived:unavailable"})
    monkeypatch.setattr(agent, "choose_champion", lambda pool: {})
    monkeypatch.setattr(agent.strat_lib, "REGISTRY", {}, raising=False)
    monkeypatch.setenv("GP_RESTRICT_MAINLINE", "1")

    out = engine_run(universe="symbols", symbols=["600519", "000001"], topk=2)
    picks = out.get("picks") or []
    candidate_pool = out.get("candidate_pool") or []
    debug = out.get("debug") or {}

    assert len(candidate_pool) == 2
    assert debug.get("restrict_to_mainline") is False
    assert all("off_mainline_downrank" not in str(item.get("reason_codes") or []) for item in picks)
