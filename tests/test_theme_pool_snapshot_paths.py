import types
import sys
import pandas as pd


def _patch_concept_to_raise(monkeypatch):
    import gp_assistant.recommend.theme_pool_impl as impl

    def raise_build(*args, **kwargs):
        raise RuntimeError("should not be called")

    monkeypatch.setattr(impl, "build_concept_themes", raise_build, raising=True)


def _patch_concept_to_return(monkeypatch, items):
    import gp_assistant.recommend.theme_pool_impl as impl
    monkeypatch.setattr(impl, "build_concept_themes", lambda *a, **k: items, raising=True)


class DummyHub:
    pass


def test_snapshot_with_industry_returns_industry_snapshot(monkeypatch):
    _patch_concept_to_raise(monkeypatch)
    from gp_assistant.recommend.theme_pool import build_themes
    # snapshot with industry and change and amount
    snap = pd.DataFrame({
        "代码": ["000001", "000002", "000003", "000004"],
        "行业": ["A", "B", "A", "B"],
        "成交额": [1e8, 2e8, 1.5e8, 5e7],
        "涨跌幅": [1.2, -0.3, 2.5, 0.4],
    })
    themes = build_themes(DummyHub(), snapshot=snap)
    assert len(themes) == 2
    assert themes[0]["source"] == "industry_snapshot"
    assert themes[0]["strength"].endswith("%") and "nan" not in themes[0]["strength"].lower()


def test_snapshot_no_industry_concept_empty_falls_back_to_top_movers(monkeypatch):
    _patch_concept_to_return(monkeypatch, [])
    from gp_assistant.recommend.theme_pool import build_themes
    snap = pd.DataFrame({
        "代码": ["000001", "000002", "000003"],
        "涨跌幅(%)": [0.1, 3.5, -1.0],
    })
    themes = build_themes(DummyHub(), snapshot=snap)
    assert len(themes) >= 1
    assert themes[0]["source"] == "top_movers"
    assert themes[0]["name"].startswith("强势线索-")


def test_snapshot_no_industry_concept_available_preferred(monkeypatch):
    fake_concepts = [
        {"name": "概念-XXX", "strength": "1.23%", "source": "concept_board_em", "evidence": []},
        {"name": "概念-YYY", "strength": "0.80%", "source": "concept_board_em", "evidence": []},
    ]
    _patch_concept_to_return(monkeypatch, fake_concepts)
    from gp_assistant.recommend.theme_pool import build_themes
    snap = pd.DataFrame({
        "代码": ["000001", "000002", "000003"],
        "涨跌幅": [0.1, 0.2, -0.1],
    })
    themes = build_themes(DummyHub(), snapshot=snap)
    assert len(themes) == len(fake_concepts)
    assert all(t["source"] == "concept_board_em" for t in themes)

