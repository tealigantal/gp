from __future__ import annotations

import pandas as pd

from src.gp_assistant.selection_engine.theme_pool_impl import build_themes_impl


def test_theme_fallback_top_movers(monkeypatch):
    # Force concept themes to return empty to trigger snapshot fallback
    import src.gp_assistant.selection_engine.theme_pool_impl as impl
    monkeypatch.setattr(impl, 'build_concept_themes', lambda *a, **k: [])

    # Snapshot with code + pct
    df = pd.DataFrame({
        'code': ['600519', '000333', '601318'],
        'pct_chg': [1.23, 0.56, 2.34],
        'chg': [None, None, None],
        'price': [None, None, None],
    })

    class DummyHub:
        pass

    themes = build_themes_impl(DummyHub(), snapshot=df, topn=2)
    assert isinstance(themes, list) and len(themes) > 0
    assert themes[0].get('source') == 'top_movers_snapshot'
