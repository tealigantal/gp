from __future__ import annotations

import pandas as pd

from src.gp_assistant.selection_engine.theme_hints import build_mover_hints
from src.providers.boards import is_mainboard


def test_is_mainboard_rules():
    for code in ["600519", "601398", "603000", "605001", "000001", "001979", "002594", "003816"]:
        assert is_mainboard(code) is True
        assert is_mainboard(code + ".SH") is True or is_mainboard(code + ".SZ") is True
    for code in ["300750", "301001", "688001", "688981", "200002", "900901"]:
        assert is_mainboard(code) is False


def test_mover_hints_filtered_to_mainboard():
    snap = pd.DataFrame(
        {
            "code": ["600519", "300750", "688001", "000001"],
            "pct_chg": [2.3, 9.9, 7.7, 1.1],
            "name": ["A", "B", "C", "D"],
        }
    )
    hints = build_mover_hints(snap, topn=10)
    syms = {str(h.get("symbol")) for h in hints}
    assert not any(s.startswith("300") or s.startswith("688") for s in syms)


def test_theme_pool_is_not_a_production_dependency():
    import src.gp_assistant.selection_engine.agent as agent

    assert not hasattr(agent, "build_themes")
