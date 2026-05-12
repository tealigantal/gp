from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
import tempfile

import pandas as pd

from gp_assistant.book import repo
from gp_assistant.contracts.objects import AdvicePick, CurrentSlotPointer, DayBook, LiveSlotArtifact, SlotDataQuality, SlotGate, TrackedUniverse
from gp_assistant.worker import boot_replay_to_current_slot, run_preopen_init


def _artifact() -> LiveSlotArtifact:
    return LiveSlotArtifact(
        artifact_id="slot_artifact_1",
        slot_id="20240320_1000",
        trade_day="20240320",
        slot_at="2024-03-20 10:00:00",
        market_phase="INTRADAY_AM",
        slot_status="OK",
        publish_allowed=True,
        daybook_effective_day="20240320",
        gate=SlotGate(state="ALLOW", score=88.0, reasons=["ok"]),
        tracked_universe=TrackedUniverse(reco=["600519"], reserve=[], portfolio=[], total=["600519"]),
        board=[],
        symbol_states={},
        data_quality=SlotDataQuality(symbols_expected=1, symbols_received=1, benchmark_received=True, provider="akshare", complete=True),
        portfolio_snapshot={},
        created_at="2024-03-20T10:00:02+08:00",
        updated_at="2024-03-20T10:00:02+08:00",
    )


def test_repo_current_pointer_round_trip(monkeypatch):
    temp_root = Path(tempfile.mkdtemp(prefix="slot_repo_", dir=str(Path.cwd())))
    monkeypatch.setenv("GP_STORE_DIR", str(temp_root / "store"))
    daybook = DayBook(trading_day="20240320", generated_at="2024-03-20T09:00:00+08:00")
    artifact = _artifact()
    try:
        repo.save_daybook(daybook)
        repo.save_slot_artifact(artifact)
        repo.save_current_pointer(
            CurrentSlotPointer(
                artifact_id=artifact.artifact_id,
                trade_day=artifact.trade_day,
                slot_id=artifact.slot_id,
                slot_at=artifact.slot_at,
                updated_at=artifact.updated_at,
            )
        )
        loaded = repo.load_current_slot_artifact()
        assert loaded is not None
        assert loaded.artifact_id == artifact.artifact_id

        book = repo.load_current_book()
        assert book is not None
        assert book.artifact_id == artifact.artifact_id
        assert book.slot_id == artifact.slot_id
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_repo_does_not_fallback_to_legacy_current_json_without_pointer(monkeypatch):
    temp_root = Path(tempfile.mkdtemp(prefix="slot_repo_legacy_", dir=str(Path.cwd())))
    monkeypatch.setenv("GP_STORE_DIR", str(temp_root / "store"))
    try:
        legacy_book = {
            "trading_day": "20240320",
            "book_version": "book_legacy_v1",
            "updated_at": "2024-03-20T10:00:00+08:00",
            "regime": {},
            "daybook": {"trading_day": "20240320", "generated_at": "2024-03-20T09:00:00+08:00", "regime": {}, "tradeable": True, "themes": [], "picks": [], "reserve_picks": [], "reserve_symbols": [], "source_meta": {}},
            "board": [],
            "watchset": [],
            "symbol_states": {},
            "portfolio_snapshot": {},
            "side_results": [],
        }
        repo.current_book_path().parent.mkdir(parents=True, exist_ok=True)
        repo.current_book_path().write_text(json.dumps(legacy_book), encoding="utf-8")
        assert repo.load_current_pointer() is None
        assert repo.load_current_book() is None
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_worker_preopen_writes_current_pointer(monkeypatch):
    temp_root = Path(tempfile.mkdtemp(prefix="slot_worker_", dir=str(Path.cwd())))
    monkeypatch.setenv("GP_STORE_DIR", str(temp_root / "store"))

    def _fake_daybook(*args, **kwargs):
        return DayBook(
            trading_day="20240320",
            generated_at="2024-03-20T09:00:00+08:00",
            picks=[],
            reserve_picks=[],
            reserve_symbols=[],
        )

    monkeypatch.setattr("gp_assistant.worker.build_daybook", _fake_daybook)
    monkeypatch.setattr("gp_assistant.worker.load_portfolio_snapshot", lambda: {"positions": []})
    monkeypatch.setattr("gp_assistant.worker.load_slot_volume_baselines", lambda trade_day, symbols: {})

    try:
        out = run_preopen_init(now=datetime(2024, 3, 20, 9, 20))
        pointer = repo.load_current_pointer()
        assert out["slot_status"] == "UNAVAILABLE"
        assert pointer is not None
        assert pointer.artifact_id == out["artifact_id"]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_boot_replay_rebuilds_closed_slots_and_updates_pointer(monkeypatch):
    temp_root = Path(tempfile.mkdtemp(prefix="slot_replay_", dir=str(Path.cwd())))
    monkeypatch.setenv("GP_STORE_DIR", str(temp_root / "store"))
    monkeypatch.setattr("gp_assistant.worker._intraday_runtime_enabled", lambda: True)

    daybook = DayBook(
        trading_day="20240320",
        generated_at="2024-03-20T09:00:00+08:00",
        picks=[
            AdvicePick(
                symbol="600519",
                rank=1,
                industry="white-liquor",
                entry_plan={"high": 10.30, "mid": 10.18},
                stop_plan={"price": 9.85},
                take_profit_plan={"targets": [10.80]},
            ),
            AdvicePick(
                symbol="000001",
                rank=2,
                industry="bank",
                entry_plan={"high": 10.28, "mid": 10.16},
                stop_plan={"price": 9.82},
                take_profit_plan={"targets": [10.70]},
            ),
        ],
        reserve_picks=[],
        reserve_symbols=[],
    )

    def _bars(base: float) -> pd.DataFrame:
        times = pd.date_range("2024-03-20 09:35:00", periods=9, freq="5min")
        rows = []
        prev = base
        for idx, ts in enumerate(times):
            close = base + 0.03 * idx
            rows.append(
                {
                    "trade_time": ts,
                    "open": prev,
                    "high": close + 0.04,
                    "low": min(prev, close) - 0.02,
                    "close": close,
                    "vol": 120 + idx * 8,
                    "amount": close * (120 + idx * 8),
                }
            )
            prev = close
        return pd.DataFrame(rows)

    bundle = {
        "bars": {
            "600519": _bars(10.0),
            "000001": _bars(10.02),
        },
        "benchmark": _bars(10.0),
        "benchmark_symbol": "000300",
        "snapshot": pd.DataFrame(
            [
                {"symbol": "600519", "pct_chg": 1.2, "chg": 1.2, "ts": pd.Timestamp("2024-03-20 10:15:00")},
                {"symbol": "000001", "pct_chg": 0.8, "chg": 0.8, "ts": pd.Timestamp("2024-03-20 10:15:00")},
            ]
        ),
        "requested_slot_at": "2024-03-20 10:15:00",
        "provider": "akshare",
        "errors": [],
        "snapshot_age_sec": 0.0,
        "symbols_expected": 2,
        "symbols_received": 2,
        "benchmark_received": True,
    }

    monkeypatch.setattr("gp_assistant.worker._load_or_build_daybook", lambda trade_day: daybook)
    monkeypatch.setattr("gp_assistant.worker.load_portfolio_snapshot", lambda: {"positions": []})
    monkeypatch.setattr("gp_assistant.worker.load_slot_volume_baselines", lambda trade_day, symbols: {symbol: {"09:35": 80.0, "09:40": 90.0, "09:45": 95.0, "09:50": 100.0, "09:55": 100.0, "10:00": 100.0, "10:05": 100.0, "10:10": 100.0, "10:15": 100.0} for symbol in symbols})
    monkeypatch.setattr("gp_assistant.worker.fetch_intraday_bundle", lambda **kwargs: bundle)

    try:
        out = boot_replay_to_current_slot(now=datetime(2024, 3, 20, 10, 17))
        pointer = repo.load_current_pointer()
        assert out["replayed_slots"] == 9
        assert pointer is not None
        assert pointer.slot_at == "2024-03-20 10:15:00"
        assert repo.load_current_slot_artifact() is not None
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_boot_replay_skips_intraday_fetch_when_runtime_disabled(monkeypatch):
    temp_root = Path(tempfile.mkdtemp(prefix="slot_replay_disabled_", dir=str(Path.cwd())))
    monkeypatch.setenv("GP_STORE_DIR", str(temp_root / "store"))
    monkeypatch.setattr("gp_assistant.worker._intraday_runtime_enabled", lambda: False)

    daybook = DayBook(
        trading_day="20240320",
        generated_at="2024-03-20T09:00:00+08:00",
        picks=[
            AdvicePick(
                symbol="600519",
                rank=1,
                industry="white-liquor",
                entry_plan={"high": 10.30, "mid": 10.18},
                stop_plan={"price": 9.85},
                take_profit_plan={"targets": [10.80]},
            )
        ],
        reserve_picks=[],
        reserve_symbols=[],
        source_meta={"daily_freshness": {"ready": True, "target_day": "2024-03-20"}},
    )

    def _unexpected_fetch(**kwargs):
        raise AssertionError("fetch_intraday_bundle should not run when intraday runtime is disabled")

    monkeypatch.setattr("gp_assistant.worker._load_or_build_daybook", lambda trade_day: daybook)
    monkeypatch.setattr("gp_assistant.worker.load_portfolio_snapshot", lambda: {"positions": []})
    monkeypatch.setattr("gp_assistant.worker.fetch_intraday_bundle", _unexpected_fetch)

    try:
        out = boot_replay_to_current_slot(now=datetime(2024, 3, 20, 10, 17), force=True)
        current = repo.load_current_slot_artifact()
        assert out["disabled"] is True
        assert out["reason"] == "intraday_runtime_disabled"
        assert out["slot_status"] == "UNAVAILABLE"
        assert out["slot_at"] == "2024-03-20 10:15:00"
        assert current is not None
        assert current.provider_meta["reason"] == "intraday_runtime_disabled"
        assert current.slot_at == "2024-03-20 10:15:00"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
