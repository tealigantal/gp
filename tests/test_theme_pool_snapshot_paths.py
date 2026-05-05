import pandas as pd


def _patch_concept_to_raise(monkeypatch):
    import gp_assistant.selection_engine.theme_pool_impl as impl

    def raise_build(*args, **kwargs):
        raise RuntimeError("should not be called")

    monkeypatch.setattr(impl, "build_concept_themes", raise_build, raising=True)


def _patch_concept_to_return(monkeypatch, items):
    import gp_assistant.selection_engine.theme_pool_impl as impl

    monkeypatch.setattr(impl, "build_concept_themes", lambda *a, **k: items, raising=True)


class DummyHub:
    pass


def test_snapshot_with_industry_returns_industry_snapshot(monkeypatch):
    _patch_concept_to_raise(monkeypatch)
    from gp_assistant.selection_engine.theme_pool import build_themes

    snap = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003", "000004"],
            "行业": ["A", "B", "A", "B"],
            "成交额": [1e8, 2e8, 1.5e8, 5e7],
            "涨跌幅": [1.2, -0.3, 2.5, 0.4],
        }
    )
    themes = build_themes(DummyHub(), snapshot=snap)
    assert len(themes) == 2
    assert themes[0]["source"] == "industry_snapshot"
    assert themes[0]["strength"].endswith("%")
    assert "nan" not in themes[0]["strength"].lower()


def test_snapshot_no_industry_concept_empty_falls_back_to_top_movers(monkeypatch):
    _patch_concept_to_return(monkeypatch, [])
    from gp_assistant.selection_engine.theme_hints import build_mover_hints
    from gp_assistant.selection_engine.theme_pool import build_themes

    snap = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003"],
            "涨跌幅(%)": [0.1, 3.5, -1.0],
        }
    )

    themes = build_themes(DummyHub(), snapshot=snap)
    assert len(themes) >= 1
    assert all(theme["source"] == "top_movers_snapshot" for theme in themes)
    assert any("000002" in theme["name"] for theme in themes)

    hints = build_mover_hints(snap, topn=2)
    assert len(hints) == 2
    assert hints[0]["source"] == "snapshot"


def test_snapshot_no_industry_concept_available_preferred(monkeypatch):
    fake_concepts = [
        {"name": "Concept-XXX", "strength": "1.23%", "source": "concept_board_em", "evidence": []},
        {"name": "Concept-YYY", "strength": "0.80%", "source": "concept_board_em", "evidence": []},
    ]
    _patch_concept_to_return(monkeypatch, fake_concepts)
    from gp_assistant.selection_engine.theme_pool import build_themes

    snap = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003"],
            "涨跌幅": [0.1, 0.2, -0.1],
        }
    )
    themes = build_themes(DummyHub(), snapshot=snap)
    assert len(themes) == len(fake_concepts)
    assert all(theme["source"] == "concept_board_em" for theme in themes)


def test_build_themes_is_impl():
    from gp_assistant.selection_engine.theme_pool import build_themes

    assert build_themes.__module__.endswith("theme_pool_impl")
