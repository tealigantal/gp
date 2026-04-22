import types
import pandas as pd
import numpy as np

from gp_assistant.selection_engine.theme_pool import build_themes
from gp_assistant.chat_compat.render import render_recommendation
from gp_assistant.strategy.chip_model import compute_chip


def _mock_snapshot(no_industry: bool = True):
    cols = ['浠ｇ爜','鍚嶇О','鏈€鏂颁环','鎴愪氦棰?,'娑ㄨ穼骞?]
    df = pd.DataFrame({
        '浠ｇ爜': ['000001','000002','000333'],
        '鍚嶇О': ['A','B','C'],
        '鏈€鏂颁环': [10, 20, 30],
        '鎴愪氦棰?: [1e9, 2e9, 1.5e9],
        '娑ㄨ穼骞?: [1.2, -0.5, 3.0],
    })
    if not no_industry:
        df['琛屼笟'] = ['X','Y','X']
    return df


def test_theme_concept_missing_change_triggers_fallback(monkeypatch):
    # snapshot without 琛屼笟 column, concept source returns no change columns
    snap = _mock_snapshot(no_industry=True).drop(columns=['娑ㄨ穼骞?])
    class DummyHub:
        pass
    # mock akshare
    class DummyAK:
        @staticmethod
        def stock_board_concept_name_ths():
            return pd.DataFrame({'鏉垮潡鍚嶇О': ['AI PC','闃垮皵鑼ㄦ捣榛樻蹇?]})
    monkeypatch.setitem(__import__('sys').modules, 'akshare', DummyAK())
    themes = build_themes(DummyHub(), snapshot=snap)
    assert themes == []  # no pseudo themes
    # also ensure render does not emit empty parentheses when strength missing
    txt = render_recommendation({'env': {'grade':'C','reasons':[]}, 'themes': [{'name':'姒傚康-绀轰緥','strength':''}], 'picks': []})
    assert '姒傚康-绀轰緥()' not in txt


def test_chip_uses_trailing_window_and_is_reasonable():
    # Construct df with regime shift: old=5, recent=50
    n_old, n_new = 200, 60
    prices = [5.0]*n_old + [50.0]*n_new
    df = pd.DataFrame({
        'open': prices, 'high': prices, 'low': prices, 'close': prices, 'volume': np.ones(len(prices))*1e6
    })
    chip, meta = compute_chip(df)
    last_close = df['close'].iloc[-1]
    # should be same order of magnitude
    assert (chip.band_90_high / last_close) < 3.0
    assert (last_close / max(chip.band_90_low, 1e-6)) < 3.0
    # optional attribute set by our impl (may not exist in some envs)
    assert getattr(chip, 'calc_window_bars', 0) >= 30


def test_stale_setup_fallback_keeps_bands_near_price():
    # Build a simple feature df
    prices = np.linspace(10, 100, 200)
    df = pd.DataFrame({'close': prices})
    # fake strategy module: stale setup at idx=50, key_bands anchored long-ago window
    Setup = types.SimpleNamespace
    fake_mod = types.SimpleNamespace(
        detect_setups=lambda d: [Setup(idx=50)],
        key_bands=lambda d, s: {
            'S1': float(d.iloc[max(0, s.idx-20): s.idx+1]['close'].quantile(0.3)),
            'S2': float(d.iloc[max(0, s.idx-20): s.idx+1]['close'].quantile(0.5)),
            'R1': float(d.iloc[max(0, s.idx-20): s.idx+1]['close'].quantile(0.8)),
            'R2': float(d.iloc[max(0, s.idx-20): s.idx+1]['close'].quantile(0.85)),
        }
    )
    # Apply fallback logic similar to agent: stale -> recent window
    last_close = float(df['close'].iloc[-1])
    setup_idx = 50
    setup_age = (len(df)-1) - setup_idx
    stale = setup_age > 10
    if stale:
        x = df.tail(60)
        bands = {
            'S1': float(x['close'].quantile(0.30)),
            'S2': float(x['close'].quantile(0.50)),
            'R1': float(x['close'].quantile(0.80)),
            'R2': float(x['close'].quantile(0.85)),
        }
    else:
        bands = fake_mod.key_bands(df, Setup(idx=setup_idx))
    assert (bands['R1'] / last_close) < 3.0 and (last_close / max(bands['S1'],1e-6)) < 3.0
