import pandas as pd


def test_infer_scale_100_when_evidence_present():
    from gp_assistant.selection_engine.chg_normalize import infer_scale_by_implied_pct, normalize_chg_pct, detect_chg_col
    df = pd.DataFrame({
        '閺堚偓閺傞鐜?: [10.0, 20.0, 30.0],
        '濞戙劏绌兼０?: [0.1, -0.2, 0.3],
        '濞戙劏绌奸獮?: [0.01, -0.01, 0.01],  # decimals
    })
    scale = infer_scale_by_implied_pct(df)
    assert scale == 100.0
    chg_col = detect_chg_col(df.columns)
    ser, ev = normalize_chg_pct(df, chg_col or '濞戙劏绌奸獮?)
    assert any('scale:implied_pct_ratio~100' in s for s in ev)
    assert abs(float(ser.iloc[0]) - 1.0) < 1e-6


def test_infer_scale_1_when_raw_is_percent():
    from gp_assistant.selection_engine.chg_normalize import infer_scale_by_implied_pct, normalize_chg_pct, detect_chg_col
    df = pd.DataFrame({
        '閺堚偓閺傞鐜?: [10.0, 20.0, 30.0],
        '濞戙劏绌兼０?: [0.1, -0.2, 0.3],
        '濞戙劏绌奸獮?: [1.0, -1.0, 1.0],  # already percent
    })
    scale = infer_scale_by_implied_pct(df)
    assert scale == 1.0
    chg_col = detect_chg_col(df.columns)
    ser, ev = normalize_chg_pct(df, chg_col or '濞戙劏绌奸獮?)
    assert any('scale:implied_pct_ratio~1' in s for s in ev)
    assert abs(float(ser.iloc[0]) - 1.0) < 1e-6


def test_no_evidence_assume_percent_and_record():
    from gp_assistant.selection_engine.chg_normalize import infer_scale_by_implied_pct, normalize_chg_pct
    df = pd.DataFrame({
        '娴狅絿鐖?: ['a', 'b', 'c'],
        '濞戙劏绌奸獮?: [1.2, -0.3, 0.5],
    })
    scale = infer_scale_by_implied_pct(df)
    assert scale is None
    ser, ev = normalize_chg_pct(df, '濞戙劏绌奸獮?)
    assert any('scale:assume_pct_no_evidence' in s for s in ev)
    assert abs(float(ser.iloc[0]) - 1.2) < 1e-6
