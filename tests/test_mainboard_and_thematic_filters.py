from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from src.providers.boards import is_mainboard
from src.gp_assistant.recommend.theme_hints import build_mover_hints
from src.gp_assistant.recommend.theme_pool import build_themes


def test_is_mainboard_rules():
    # Mainboard should pass
    for code in ["600519", "601398", "603000", "605001", "000001", "001979", "002594", "003816"]:
        assert is_mainboard(code) is True
        assert is_mainboard(code + ".SH") is True or is_mainboard(code + ".SZ") is True
    # ChiNext/STAR should fail
    for code in ["300750", "301001", "688001", "688981", "200002", "900901"]:
        assert is_mainboard(code) is False


def test_mover_hints_filtered_to_mainboard():
    snap = pd.DataFrame(
        {
            "code": ["600519", "300750", "688001", "000001"],
            "涨跌幅": [2.3, 9.9, 7.7, 1.1],
            "name": ["贵州茅台", "宁德时代", "某科创", "平安银行"],
        }
    )
    hints = build_mover_hints(snap, topn=10)
    syms = {str(h.get("symbol")) for h in hints}
    # No 300/301/688 in mover hints
    assert not any(s.startswith("300") or s.startswith("688") for s in syms)


def test_theme_pool_impl_uses_mainboard_only(monkeypatch):
    class DummyHub:  # not used by impl
        pass

    snap = pd.DataFrame(
        {
            "代码": ["600519", "300750", "000001"],
            "行业": ["白酒", "新能源", "银行"],
            "涨跌幅": [2.2, 8.8, 0.9],
            "成交额": [1e9, 2e9, 3e9],
        }
    )
    themes = build_themes(DummyHub(), snapshot=snap)
    # Top2 themes must derive from mainboard codes only (300750 excluded)
    names = [t.get("name") for t in themes]
    assert set(names).issubset({"白酒", "银行"})

