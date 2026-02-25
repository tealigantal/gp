import types
import sys
import pandas as pd


def _install_fake_akshare(monkeypatch, funcs: dict):
    mod = types.ModuleType("akshare")
    for k, v in funcs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, "akshare", mod)
    return mod


class DummyHub:
    pass


def test_build_themes_snapshot_none_uses_concept_em(monkeypatch):
    def em_df():
        return pd.DataFrame({
            "板块名称": ["AI算力", "短剧经济", "次新股"],
            "涨跌幅": [3.21, 2.1, -0.5],
        })

    _install_fake_akshare(monkeypatch, {"stock_board_concept_name_em": em_df})

    from gp_assistant.recommend.theme_pool import build_themes

    themes = build_themes(DummyHub(), snapshot=None)
    assert len(themes) == 2
    assert themes[0]["source"] == "concept_board_em"
    assert themes[0]["name"].startswith("概念-")
    assert themes[0]["strength"].endswith("%") and "nan" not in themes[0]["strength"].lower()


def test_build_themes_snapshot_missing_chg_col_uses_concept(monkeypatch):
    def em_df():
        return pd.DataFrame({
            "板块名称": ["机器人", "卫星互联网", "虚拟电厂"],
            "涨跌幅(%)": [1.2, 1.1, 0.6],
        })

    _install_fake_akshare(monkeypatch, {"stock_board_concept_name_em": em_df})

    from gp_assistant.recommend.theme_pool import build_themes

    # Snapshot without any change column
    snapshot = pd.DataFrame({
        "代码": ["000001", "000002"],
        "名称": ["平安银行", "万科A"],
        "成交额": [1.2e9, 9.8e8],
    })
    themes = build_themes(DummyHub(), snapshot=snapshot)
    assert len(themes) == 2
    assert all(t["name"].startswith("概念-") for t in themes)


def test_concept_em_fails_fallback_to_ths_source(monkeypatch):
    def em_fail():
        raise RuntimeError("network down")

    def ths_df():
        return pd.DataFrame({
            "板块名称": ["芯片", "云计算"],
            "涨跌": [2.8, 1.5],
        })

    _install_fake_akshare(monkeypatch, {
        "stock_board_concept_name_em": em_fail,
        "stock_board_concept_name_ths": ths_df,
    })

    from gp_assistant.recommend.theme_pool import build_themes

    themes = build_themes(DummyHub(), snapshot=None)
    assert len(themes) == 2
    assert themes[0]["source"] == "concept_board_ths"


def test_concept_no_rank_col_returns_empty_no_pseudo(monkeypatch):
    def em_df_no_rank():
        return pd.DataFrame({
            "板块名称": ["低空经济", "无人驾驶"],
        })

    _install_fake_akshare(monkeypatch, {"stock_board_concept_name_em": em_df_no_rank})

    from gp_assistant.recommend.theme_pool import build_themes

    themes = build_themes(DummyHub(), snapshot=None)
    assert themes == []

