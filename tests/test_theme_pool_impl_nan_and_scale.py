import pandas as pd


def test_industry_strength_handles_nan_and_scales_decimal():
    from gp_assistant.selection_engine.theme_pool_impl import build_themes_impl

    # snapshot with industry and decimal change (0.01 -> 1%) and NaN rows
    # include evidence columns to infer scaling (implied ~100x)
    snap = pd.DataFrame({
        "娴狅絿鐖?: ["a", "b", "c", "d"],
        "鐞涘奔绗?: ["X", "X", "Y", "Y"],
        "濞戙劏绌兼０?: [0.1, None, 0.2, 0.0],
        "閺堚偓閺傞鐜?: [10.0, 10.0, 10.0, 10.0],
        "濞戙劏绌奸獮?: [0.01, None, 0.02, 0.0],
        "閹存劒姘︽０?: [1e7, 2e7, 1e7, 1e7],
    })
    themes = build_themes_impl(hub=None, snapshot=snap, topn=2)  # type: ignore[arg-type]
    assert len(themes) == 2
    assert all(t["source"] == "industry_snapshot" for t in themes)
    # strength should be percentages and not 'nan%'
    for t in themes:
        assert t["strength"].endswith('%') and 'nan' not in t["strength"].lower()
    # evidence includes implied scaling when applied
    assert any(any('scale:implied_pct_ratio~100' in s for s in (t.get('evidence') or [])) for t in themes)
