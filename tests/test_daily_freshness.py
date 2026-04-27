from __future__ import annotations

import pandas as pd

from gp_assistant.evidence import daily_freshness
from gp_assistant.evidence import market_service


def test_reconcile_daily_freshness_marks_failed_refresh(monkeypatch):
    reports = {
        "600000": {"freshness_state": "stale", "last_item_time": "2026-04-21", "last_fetch_at": "2026-04-22T10:00:00"},
        "600519": {"freshness_state": "current", "last_item_time": "2026-04-27", "last_fetch_at": "2026-04-27T19:00:00"},
    }

    monkeypatch.setattr(daily_freshness, "inspect_symbol_freshness", lambda symbol, **_: {"symbol": symbol, **reports[symbol], "target_trading_day": "2026-04-27"})

    class _Hub:
        def daily_ohlcv(self, symbol, **kwargs):
            if symbol == "600000":
                raise RuntimeError("network down")
            return pd.DataFrame({"date": ["2026-04-27"], "open": [1], "high": [1], "low": [1], "close": [1], "volume": [1], "amount": [1]}), {
                "len": 1,
                "source": "store+network_merge",
                "freshness_state": "current",
                "refresh_attempted": False,
                "refresh_succeeded": True,
            }

    monkeypatch.setattr(daily_freshness, "MarketDataHub", _Hub)
    monkeypatch.setattr(daily_freshness, "save_daily_freshness_report", lambda report: None)

    report = daily_freshness.reconcile_daily_freshness(["600000", "600519"], as_of="2026-04-27")

    assert report["ready"] is False
    assert "600000" in report["failed_symbols"]
    assert "600000" in report["stale_symbols"]
    assert "600519" in report["fresh_symbols"]


def test_audit_daily_freshness_focus_symbols(monkeypatch):
    monkeypatch.setattr(
        daily_freshness,
        "inspect_symbol_freshness",
        lambda symbol, **_: {
            "symbol": symbol,
            "target_trading_day": "2026-04-27",
            "last_fetch_at": "2026-04-27T19:35:00+08:00",
            "last_item_time": "2026-04-21" if symbol == "002716" else "2026-04-27",
            "freshness_state": "stale" if symbol == "002716" else "current",
        },
    )

    audit = daily_freshness.audit_daily_freshness(symbols=["002716", "002371"], as_of="2026-04-27", limit=5)

    assert audit["target_day"] == "2026-04-27"
    assert audit["focus_stale_symbols"] == ["002716"]


def test_build_day_selection_blocks_when_daily_not_ready(monkeypatch):
    monkeypatch.setattr(
        market_service,
        "run_selection",
        lambda **_: {
            "tradeable": True,
            "picks": [{"symbol": "002716", "score": 0.91}],
            "candidate_pool": [{"symbol": "002716", "score": 0.91}],
            "debug": {},
        },
    )
    monkeypatch.setattr(
        market_service,
        "reconcile_daily_freshness",
        lambda symbols, **_: {
            "ready": False,
            "target_day": "2026-04-27",
            "checked_symbols": list(symbols),
            "fresh_symbols": [],
            "stale_symbols": ["002716"],
            "failed_symbols": ["002716"],
            "refreshed_symbols": [],
            "symbol_reports": [
                {
                    "symbol": "002716",
                    "last_item_time": "2026-04-21",
                    "freshness_state": "failed_refresh",
                }
            ],
            "blocking_reason": "日线数据未补齐到目标交易日 2026-04-27：002716",
        },
    )

    result = market_service.build_day_selection("20260427", topk=3)

    assert result["tradeable"] is False
    assert result["reason"] == "daily_freshness_blocked"
    assert result["picks"] == []
    assert result["candidate_pool"] == []
    assert result["daily_freshness"]["ready"] is False
    assert "日线数据未补齐到目标交易日" in result["message"]
