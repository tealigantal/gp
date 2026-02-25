import pandas as pd


def test_industry_strength_handles_nan_and_scales_decimal():
    from gp_assistant.recommend.theme_pool_impl import build_themes_impl

    # snapshot with industry and decimal change (0.01 -> 1%) and NaN rows
    # include evidence columns to infer scaling (implied ~100x)
    snap = pd.DataFrame({
        "代码": ["a", "b", "c", "d"],
        "行业": ["X", "X", "Y", "Y"],
        "涨跌额": [0.1, None, 0.2, 0.0],
        "最新价": [10.0, 10.0, 10.0, 10.0],
        "涨跌幅": [0.01, None, 0.02, 0.0],
        "成交额": [1e7, 2e7, 1e7, 1e7],
    })
    themes = build_themes_impl(hub=None, snapshot=snap, topn=2)  # type: ignore[arg-type]
    assert len(themes) == 2
    assert all(t["source"] == "industry_snapshot" for t in themes)
    # strength should be percentages and not 'nan%'
    for t in themes:
        assert t["strength"].endswith('%') and 'nan' not in t["strength"].lower()
    # evidence includes implied scaling when applied
    assert any(any('scale:implied_pct_ratio~100' in s for s in (t.get('evidence') or [])) for t in themes)
