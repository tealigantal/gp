import pandas as pd


def test_industry_strength_handles_nan_and_scales_decimal():
    from gp_assistant.selection_engine.theme_pool_impl import build_themes_impl

    snap = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003", "000004"],
            "行业": ["X", "X", "Y", "Y"],
            "涨跌额": [0.1, None, 0.2, 0.0],
            "最新价": [10.0, 10.0, 10.0, 10.0],
            "涨跌幅": [0.01, None, 0.02, 0.0],
            "成交额": [1e7, 2e7, 1e7, 1e7],
        }
    )
    themes = build_themes_impl(hub=None, snapshot=snap, topn=2)  # type: ignore[arg-type]
    assert len(themes) == 2
    assert all(t["source"] == "industry_snapshot" for t in themes)
    for theme in themes:
        assert theme["strength"].endswith("%")
        assert "nan" not in theme["strength"].lower()
    assert any(
        any("scale:implied_pct_ratio~100" in s for s in (theme.get("evidence") or []))
        for theme in themes
    )
