import types
import pandas as pd

from src.gp_assistant.recommend.theme_concept import build_concept_themes, last_concept_status
from src.gp_assistant.recommend.mainline import build_mainline


def _mock_akshare_for_theme(monkeypatch):
    ak = types.SimpleNamespace()
    def industry_name_em():
        return pd.DataFrame({
            "板块名称": ["有色金属", "半导体"],
            "板块代码": ["BK001", "BK002"],
            "涨跌幅": [2.5, 1.0],
            "领涨股": ["紫金矿业", "韦尔股份"],
            "领涨股-涨跌幅": ["3.5%", "2.0%"],
        })
    def concept_name_em():
        return pd.DataFrame({
            "板块名称": ["ChatGPT", "光刻机"],
            "板块代码": ["BK101", "BK102"],
            "涨跌幅": [5.5, -0.5],
            "领涨股": ["科大讯飞", "北方华创"],
            "领涨股-涨跌幅": ["7.0%", "-1.0%"],
        })
    ak.stock_board_industry_name_em = industry_name_em
    ak.stock_board_concept_name_em = concept_name_em
    ak.stock_board_industry_cons_em = lambda symbol: pd.DataFrame({"代码": ["000001"], "名称": ["平安银行"], "涨跌幅": [1.0]})
    ak.stock_board_concept_cons_em = lambda symbol: pd.DataFrame({"代码": ["600519"], "名称": ["贵州茅台"], "涨跌幅": [0.5]})
    monkeypatch.setitem(__import__('sys').modules, 'akshare', ak)


def _mock_akshare_for_mainline(monkeypatch):
    ak = types.SimpleNamespace()
    def stock_sector_fund_flow_rank(indicator: str, sector_type: str):
        return pd.DataFrame({
            "名称": ["有色金属", "半导体"],
            "主力净流入-净额": ["12,345", "10,000"],
            "涨跌幅": [2.3, -1.2],
            "领涨股": ["紫金矿业", "韦尔股份"],
        })
    ak.stock_sector_fund_flow_rank = stock_sector_fund_flow_rank
    monkeypatch.setitem(__import__('sys').modules, 'akshare', ak)


def test_theme_concept_no_spot_call_without_symbol(monkeypatch):
    _mock_akshare_for_theme(monkeypatch)
    themes = build_concept_themes(topn=2)
    assert isinstance(themes, list)
    assert len(themes) >= 1
    lcs = last_concept_status()
    assert "concept_spot_em" not in (lcs.get("attempted") or [])


def test_mainline_builder(monkeypatch):
    _mock_akshare_for_mainline(monkeypatch)
    res = build_mainline(indicator="今日", topn=2)
    assert isinstance(res, dict)
    assert len(res.get("sectors") or []) > 0

