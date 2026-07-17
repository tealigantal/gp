from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from gp_assistant.evidence import daily_freshness
from gp_assistant.evidence import market_service
import gp_assistant.runtime.market_clock as market_clock
from gp_assistant.runtime.market_clock import PHASE_INTRADAY_PM, PHASE_NON_TRADING, PHASE_POSTCLOSE_PENDING


def test_resolve_daily_target_intraday_uses_previous_completed(monkeypatch):
    state = SimpleNamespace(
        market_phase=PHASE_INTRADAY_PM,
        target_daybook_effective_day="20260430",
        target_pulse_trade_day="20260430",
        target_pulse_slot_at="2026-04-30 13:15:00",
    )
    monkeypatch.setattr(daily_freshness, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(daily_freshness, "_previous_open_day_ymd", lambda ymd: "20260429")

    target = daily_freshness.resolve_daily_target("2026-04-30")

    assert target["target_day"] == "2026-04-29"
    assert target["target_mode"] == "previous_completed"
    assert target["daybook_trading_day"] == "20260430"


def test_resolve_daily_target_postclose_pending_waits_for_eod(monkeypatch):
    state = SimpleNamespace(
        market_phase=PHASE_POSTCLOSE_PENDING,
        target_daybook_effective_day="20260430",
        target_pulse_trade_day="20260430",
        target_pulse_slot_at="2026-04-30 14:55:00",
    )
    monkeypatch.setattr(daily_freshness, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(daily_freshness, "_previous_open_day_ymd", lambda ymd: "20260429")
    monkeypatch.setattr(
        daily_freshness,
        "probe_eod_daily_ready",
        lambda target_day, force=False: {"target_day": "2026-04-30", "ready": False, "ok_count": 1},
    )

    target = daily_freshness.resolve_daily_target("2026-04-30")

    assert target["target_day"] == "2026-04-29"
    assert target["target_mode"] == "current_pending"
    assert target["pending_eod_day"] == "2026-04-30"


def test_resolve_daily_target_postclose_ready_uses_current_day(monkeypatch):
    state = SimpleNamespace(
        market_phase=PHASE_POSTCLOSE_PENDING,
        target_daybook_effective_day="20260430",
        target_pulse_trade_day="20260430",
        target_pulse_slot_at="2026-04-30 14:55:00",
    )
    monkeypatch.setattr(daily_freshness, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(
        daily_freshness,
        "probe_eod_daily_ready",
        lambda target_day, force=False: {"target_day": "2026-04-30", "ready": True, "ok_count": 3},
    )

    target = daily_freshness.resolve_daily_target("2026-04-30")

    assert target["target_day"] == "2026-04-30"
    assert target["target_mode"] == "current_ready"
    assert target["pending_eod_day"] is None


def test_resolve_daily_target_rejects_partial_positive_eod_probe(monkeypatch):
    state = SimpleNamespace(
        market_phase=PHASE_POSTCLOSE_PENDING,
        target_daybook_effective_day="20260430",
        target_pulse_trade_day="20260430",
        target_pulse_slot_at="2026-04-30 14:55:00",
    )
    monkeypatch.setattr(daily_freshness, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(daily_freshness, "_previous_open_day_ymd", lambda ymd: "20260429")
    monkeypatch.setattr(
        daily_freshness,
        "probe_eod_daily_ready",
        lambda target_day, force=False: {
            "target_day": "2026-04-30",
            "ready": True,
            "ok_count": 2,
            "checks": [
                {"symbol": "000001", "last": "2026-04-29", "ready": False},
                {"symbol": "600000", "last": "2026-04-30", "ready": True},
                {"symbol": "600519", "last": "2026-04-30", "ready": True},
            ],
        },
    )

    target = daily_freshness.resolve_daily_target("2026-04-30")

    assert target["target_day"] == "2026-04-29"
    assert target["target_mode"] == "current_pending"
    assert target["pending_eod_day"] == "2026-04-30"


def test_resolve_daily_target_holiday_uses_previous_completed_day(monkeypatch):
    cal = pd.DataFrame(
        [
            {"cal_date": "20260430", "is_open": 1},
            {"cal_date": "20260501", "is_open": 0},
            {"cal_date": "20260502", "is_open": 0},
            {"cal_date": "20260503", "is_open": 0},
            {"cal_date": "20260504", "is_open": 0},
            {"cal_date": "20260505", "is_open": 0},
            {"cal_date": "20260506", "is_open": 1},
        ]
    )
    monkeypatch.setattr(market_clock, "_load_calendar_df", lambda: cal)

    target = daily_freshness.resolve_daily_target(now=datetime(2026, 5, 4, 10, 0))

    assert target["target_day"] == "2026-04-30"
    assert target["target_mode"] == "previous_completed"
    assert target["daybook_trading_day"] == "20260430"
    assert target["next_trading_day"] == "2026-05-06"


def test_active_freshness_discards_stale_holiday_target_when_book_matches_current(monkeypatch):
    state = SimpleNamespace(
        market_phase=PHASE_NON_TRADING,
        target_daybook_effective_day="20260430",
        target_pulse_trade_day=None,
        target_pulse_slot_at=None,
        calendar_status="ok",
        calendar_source="official",
        calendar_range_start="20250101",
        calendar_range_end="20261231",
        next_trading_day="20260506",
        calendar_error=None,
    )
    monkeypatch.setattr(daily_freshness, "compute_market_state", lambda now=None: state)
    stale = {
        "ready": False,
        "target_day": "2026-05-04",
        "blocking_reason": "日线数据未补齐到 2026-05-04，当前不发布正式推荐",
    }

    active = daily_freshness.active_freshness_for_current_target(stale, book_day="20260430")

    assert active == {}


def test_resolve_daily_target_reads_cached_eod_probe_without_network(monkeypatch):
    state = SimpleNamespace(
        market_phase=PHASE_POSTCLOSE_PENDING,
        target_daybook_effective_day="20260430",
        target_pulse_trade_day="20260430",
        target_pulse_slot_at="2026-04-30 14:55:00",
    )
    cached_probe = {"target_day": "2026-04-30", "ready": True, "ok_count": 3}
    monkeypatch.setattr(daily_freshness, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(daily_freshness, "_read_eod_probe_cache", lambda target_day, ttl_sec: cached_probe)
    monkeypatch.setattr(
        daily_freshness,
        "probe_eod_daily_ready",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("network probe should not run")),
    )

    target = daily_freshness.resolve_daily_target("2026-04-30", allow_probe=False)

    assert target["target_day"] == "2026-04-30"
    assert target["target_mode"] == "current_ready"
    assert target["eod_probe"] == cached_probe


def test_expired_positive_eod_probe_stays_ready_for_same_target(monkeypatch, tmp_path):
    probe_path = tmp_path / "eod_daily_probe.json"
    probe = {
        "target_day": "2026-04-30",
        "ready": True,
        "checked_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "ok_count": 3,
    }
    probe_path.write_text(json.dumps(probe), encoding="utf-8")
    monkeypatch.setattr(daily_freshness, "_eod_probe_path", lambda: probe_path)

    cached = daily_freshness._read_eod_probe_cache("2026-04-30", ttl_sec=30)

    assert cached == probe


def test_eod_probe_cache_rejects_partial_positive_checks(monkeypatch, tmp_path):
    probe_path = tmp_path / "eod_daily_probe.json"
    probe = {
        "target_day": "2026-04-30",
        "ready": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "ok_count": 2,
        "checks": [
            {"symbol": "000001", "last": "2026-04-29", "ready": False},
            {"symbol": "600000", "last": "2026-04-30", "ready": True},
            {"symbol": "600519", "last": "2026-04-30", "ready": True},
        ],
    }
    probe_path.write_text(json.dumps(probe), encoding="utf-8")
    monkeypatch.setattr(daily_freshness, "_eod_probe_path", lambda: probe_path)

    cached = daily_freshness._read_eod_probe_cache("2026-04-30", ttl_sec=300)

    assert cached is None


def test_probe_eod_daily_ready_requires_all_probe_symbols(monkeypatch, tmp_path):
    probe_path = tmp_path / "eod_daily_probe.json"

    class _Hub:
        def daily_ohlcv(self, symbol, **kwargs):
            last = "2026-04-29" if symbol == "000001" else "2026-04-30"
            return pd.DataFrame({"date": [last], "open": [1], "high": [1], "low": [1], "close": [1], "volume": [1], "amount": [1]}), {}

    monkeypatch.setattr(daily_freshness, "MarketDataHub", _Hub)
    monkeypatch.setattr(daily_freshness, "_eod_probe_path", lambda: probe_path)

    probe = daily_freshness.probe_eod_daily_ready("2026-04-30", force=True)

    assert probe["ready"] is False
    assert probe["ok_count"] == 2
    assert probe["next_retry_after"]
    assert any(item["symbol"] == "000001" and item["ready"] is False for item in probe["checks"])


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
    monkeypatch.setattr(daily_freshness, "_history_db_path", lambda: Path("__missing_history_for_daily_freshness_test__.db"))
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
        "run_market_memory_selection",
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


def test_build_day_selection_disables_snapshot_universe(monkeypatch):
    calls: list[dict] = []

    def fake_selection(**kwargs):
        calls.append(dict(kwargs))
        return {
            "tradeable": False,
            "picks": [],
            "candidate_pool": [],
            "debug": {},
        }

    monkeypatch.setattr(market_service, "run_market_memory_selection", fake_selection)
    monkeypatch.setattr(
        market_service,
        "reconcile_daily_freshness",
        lambda symbols, **_: {
            "ready": True,
            "target_day": "2026-04-27",
            "checked_symbols": list(symbols),
            "fresh_symbols": [],
            "stale_symbols": [],
            "failed_symbols": [],
            "refreshed_symbols": [],
            "symbol_reports": [],
            "blocking_reason": None,
        },
    )

    market_service.build_day_selection("20260427", topk=3)

    assert calls
    assert calls[0]["allow_snapshot"] is False
