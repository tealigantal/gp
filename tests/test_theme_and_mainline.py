import types
import pandas as pd

from src.gp_assistant.selection_engine.theme_concept import build_concept_themes, last_concept_status
from src.gp_assistant.selection_engine.mainline import build_mainline


def _mock_akshare_for_theme(monkeypatch):
    ak = types.SimpleNamespace()
    def industry_name_em():
        return pd.DataFrame({
            "閺夊灝娼￠崥宥囆?: ["閺堝澹婇柌鎴濈潣", "閸楀﹤顕辨担?],
            "閺夊灝娼℃禒锝囩垳": ["BK001", "BK002"],
            "濞戙劏绌奸獮?: [2.5, 1.0],
            "妫板棙瀹氶懖?: ["缁鳖偊鍣鹃惌澶哥瑹", "闂婏箑鐨甸懖鈥插敜"],
            "妫板棙瀹氶懖?濞戙劏绌奸獮?: ["3.5%", "2.0%"],
        })
    def concept_name_em():
        return pd.DataFrame({
            "閺夊灝娼￠崥宥囆?: ["ChatGPT", "閸忓鍩㈤張?],
            "閺夊灝娼℃禒锝囩垳": ["BK101", "BK102"],
            "濞戙劏绌奸獮?: [5.5, -0.5],
            "妫板棙瀹氶懖?: ["缁夋垵銇囩拋顖烆棧", "閸栨鏌熼崡搴″灡"],
            "妫板棙瀹氶懖?濞戙劏绌奸獮?: ["7.0%", "-1.0%"],
        })
    ak.stock_board_industry_name_em = industry_name_em
    ak.stock_board_concept_name_em = concept_name_em
    ak.stock_board_industry_cons_em = lambda symbol: pd.DataFrame({"娴狅絿鐖?: ["000001"], "閸氬秶袨": ["楠炲啿鐣ㄩ柧鎯邦攽"], "濞戙劏绌奸獮?: [1.0]})
    ak.stock_board_concept_cons_em = lambda symbol: pd.DataFrame({"娴狅絿鐖?: ["600519"], "閸氬秶袨": ["鐠愰潧绐為懠鍛酱"], "濞戙劏绌奸獮?: [0.5]})
    monkeypatch.setitem(__import__('sys').modules, 'akshare', ak)


def _mock_akshare_for_mainline(monkeypatch):
    ak = types.SimpleNamespace()
    def stock_sector_fund_flow_rank(indicator: str, sector_type: str):
        return pd.DataFrame({
            "閸氬秶袨": ["閺堝澹婇柌鎴濈潣", "閸楀﹤顕辨担?],
            "娑撹濮忛崙鈧ù浣稿弳-閸戔偓妫?: ["12,345", "10,000"],
            "濞戙劏绌奸獮?: [2.3, -1.2],
            "妫板棙瀹氶懖?: ["缁鳖偊鍣鹃惌澶哥瑹", "闂婏箑鐨甸懖鈥插敜"],
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
    res = build_mainline(indicator="娴犲﹥妫?, topn=2)
    assert isinstance(res, dict)
    assert len(res.get("sectors") or []) > 0
