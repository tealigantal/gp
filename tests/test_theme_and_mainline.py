from __future__ import annotations

import time

from src.gp_assistant.selection_engine import mainline


def test_mainline_builder_accepts_cached_result(monkeypatch):
    monkeypatch.setattr(
        mainline,
        "_read_cache",
        lambda indicator: {
            "indicator": indicator,
            "sectors": [{"name": "消费", "source": "cache"}],
            "source": "cache:disk",
            "errors": [],
            "ts": time.time(),
        },
    )
    res = mainline.build_mainline(indicator="today", topn=2)
    assert isinstance(res, dict)
    assert len(res.get("sectors") or []) == 1
    assert res["sectors"][0]["name"] == "消费"
