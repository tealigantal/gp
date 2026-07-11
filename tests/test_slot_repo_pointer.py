from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace

from gp_assistant.book import repo
from gp_assistant.contracts.objects import CurrentSlotPointer, DayBook, LiveSlotArtifact, SlotDataQuality, SlotGate, TrackedUniverse
from gp_assistant.worker import boot_replay_to_current_slot, run_preopen_init
from gp_assistant.runtime.producer import producer_metadata


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
        producer=producer_metadata(),
    )


def test_repo_current_pointer_round_trip(monkeypatch):
    temp_root = Path(tempfile.mkdtemp(prefix="slot_repo_", dir=str(Path.cwd())))
    monkeypatch.setenv("GP_STORE_DIR", str(temp_root / "store"))
    daybook = DayBook(trading_day="20240320", generated_at="2024-03-20T09:00:00+08:00", source_meta={"decision": "no_trade"}, producer=producer_metadata())
    artifact = _artifact()
    try:
        repo.publish_current_bundle(daybook, artifact)
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
            source_meta={"decision": "no_trade"},
            producer=producer_metadata(),
        )

    monkeypatch.setattr(
        "gp_assistant.worker.compute_market_state",
        lambda now=None: SimpleNamespace(
            market_phase="PREOPEN",
            target_daybook_effective_day="20240320",
            target_pulse_trade_day="20240320",
            target_pulse_slot_at=None,
        ),
    )
    monkeypatch.setattr("gp_assistant.worker.build_daybook", _fake_daybook)
    monkeypatch.setattr("gp_assistant.worker.load_portfolio_snapshot", lambda: {"positions": []})

    try:
        out = run_preopen_init()
        pointer = repo.load_current_pointer()
        assert out["slot_status"] == "UNAVAILABLE"
        assert pointer is not None
        assert pointer.artifact_id == out["artifact_id"]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_boot_replay_to_current_slot_is_runtime_chain_compat_alias(monkeypatch):
    calls: list[bool] = []

    def _fake_preopen(*, now=None, force=False):
        calls.append(force)
        return {
            "runtime_chain": True,
            "runtime_stage": "minute",
            "slot_status": "OK",
        }

    monkeypatch.setattr("gp_assistant.worker.run_preopen_init", _fake_preopen)

    out = boot_replay_to_current_slot(force=True)

    assert calls == [True]
    assert out["runtime_chain"] is True
    assert out["replay_disabled"] is True
    assert out["message"] == "本次按日线计划链路处理。"
