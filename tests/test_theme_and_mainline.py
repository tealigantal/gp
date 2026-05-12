from __future__ import annotations

import pandas as pd

from src.gp_assistant.selection_engine import mainline


def test_mainline_builder_derives_from_candidates():
    candidates = [
        {"symbol": "600001", "name": "A", "industry": "工业", "candidate_score": 0.8, "industry_strength_score": 0.7, "peer_consensus_score": 0.5},
        {"symbol": "600002", "name": "B", "industry": "工业", "candidate_score": 0.6, "industry_strength_score": 0.5, "peer_consensus_score": 0.4},
        {"symbol": "000001", "name": "C", "industry": "金融", "candidate_score": 0.4, "industry_strength_score": 0.2, "peer_consensus_score": 0.1},
    ]
    res = mainline.build_mainline(indicator="today", topn=2, candidates=candidates)
    assert res["source"] == "derived:daily_universe"
    assert res["sectors"][0]["name"] == "工业"


def test_mainline_builder_derives_from_snapshot_without_theme_api():
    snapshot = pd.DataFrame(
        {
            "code": ["600001", "000001", "300001"],
            "name": ["A", "B", "C"],
            "pct_chg": [2.1, 1.3, 9.9],
            "amount": [10_000_000, 20_000_000, 30_000_000],
        }
    )
    res = mainline.build_mainline(indicator="today", topn=2, snapshot=snapshot)
    assert res["source"] == "derived:market_snapshot"
    assert all(str(item["source"]).startswith("derived:") for item in res["sectors"])
    assert not any(item.get("leader_stock") == "300001" for item in res["sectors"])
