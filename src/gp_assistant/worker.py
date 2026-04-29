from __future__ import annotations

import time
from typing import Any, Dict, Optional

import pandas as pd

from .book.board import build_board
from .book.daybook import build_daybook
from .book.pulse5m import evaluate_slot_pulses, score_intraday_gate
from .book.readonly import build_unavailable_artifact
from .book.repo import (
    compose_market_book,
    load_current_slot_artifact,
    load_daybook,
    save_book,
    save_current_pointer,
    save_daybook,
    save_slot_artifact,
)
from .book.side_results import detect_side_results
from .book.watchset import build_watchset
from .contracts.objects import (
    CurrentSlotPointer,
    DayBook,
    LiveSlotArtifact,
    SlotDataQuality,
    SlotGate,
    TrackedUniverse,
)
from .core.config import load_config
from .core.logging import logger
from .evidence.daily_freshness import daybook_symbols, reconcile_daily_freshness
from .evidence.market_service import build_slot_breadth_snapshot, fetch_intraday_bundle, load_slot_volume_baselines
from .evidence.portfolio_service import load_portfolio_snapshot
from .runtime.lanes import book_lane
from .runtime.market_clock import (
    PHASE_CLOSING_AUCTION,
    PHASE_INTRADAY_AM,
    PHASE_INTRADAY_PM,
    PHASE_LUNCH_BREAK,
    PHASE_OPEN_NO_FIRST_BAR,
    PHASE_POSTCLOSE_PENDING,
    PHASE_PREOPEN,
    compute_market_state,
    iter_trade_slots,
    last_closed_trade_slot,
    next_trade_slot,
    slot_id_for,
)
from .runtime.utils import gen_id, now_iso

INTRADAY_RUNTIME_DISABLED_REASON = "intraday_runtime_disabled"


def _portfolio_symbols(snapshot: Dict[str, Any]) -> list[str]:
    return [
        str(item.get("symbol")).strip()
        for item in (snapshot.get("positions") or [])
        if str(item.get("symbol") or "").strip()
    ]


def _tracked_universe(daybook: DayBook, portfolio_snapshot: Dict[str, Any]) -> TrackedUniverse:
    cfg = load_config()
    holdings = _portfolio_symbols(portfolio_snapshot) if getattr(cfg, "intraday_include_portfolio", True) else []
    total = build_watchset(
        compose_market_book(
            daybook,
            LiveSlotArtifact(
                artifact_id="bootstrap",
                trade_day=daybook.trading_day,
                market_phase=compute_market_state().market_phase,
                daybook_effective_day=daybook.trading_day,
                created_at=now_iso(),
                updated_at=now_iso(),
            ),
        ),
        hot_symbols=[],
        holdings=holdings,
    )
    return TrackedUniverse(
        reco=[pick.symbol for pick in daybook.picks[:10]],
        reserve=[pick.symbol for pick in daybook.reserve_picks[:2]] or list(daybook.reserve_symbols[:2]),
        portfolio=holdings,
        total=total,
    )


def _data_quality(bundle: Dict[str, Any]) -> SlotDataQuality:
    return SlotDataQuality(
        snapshot_age_sec=bundle.get("snapshot_age_sec"),
        symbols_expected=int(bundle.get("symbols_expected") or 0),
        symbols_received=int(bundle.get("symbols_received") or 0),
        benchmark_received=bool(bundle.get("benchmark_received")),
        provider=str(bundle.get("provider") or "akshare"),
        complete=(
            int(bundle.get("symbols_expected") or 0) == int(bundle.get("symbols_received") or 0)
            and bool(bundle.get("benchmark_received"))
            and bundle.get("snapshot") is not None
            and not bundle["snapshot"].empty
        ),
        errors=[str(item) for item in (bundle.get("errors") or []) if str(item).strip()],
    )


def _save_artifact(daybook: DayBook, artifact: LiveSlotArtifact) -> Dict[str, Any]:
    save_daybook(daybook)
    save_slot_artifact(artifact)
    save_current_pointer(
        CurrentSlotPointer(
            artifact_id=artifact.artifact_id,
            trade_day=artifact.trade_day,
            slot_id=artifact.slot_id,
            slot_at=artifact.slot_at,
            updated_at=artifact.updated_at,
        )
    )
    save_book(compose_market_book(daybook, artifact))
    return {
        "artifact_id": artifact.artifact_id,
        "slot_id": artifact.slot_id,
        "slot_at": artifact.slot_at,
        "slot_status": artifact.slot_status,
        "gate": artifact.gate.state,
        "publish_allowed": artifact.publish_allowed,
    }


def _load_or_build_daybook(trade_day: str) -> DayBook:
    daybook = load_daybook(trade_day)
    freshness = dict(daybook.source_meta.get("daily_freshness") or {}) if daybook is not None else {}
    should_rebuild = (
        daybook is None
        or not freshness
        or freshness.get("target_day") != f"{trade_day[:4]}-{trade_day[4:6]}-{trade_day[6:8]}"
        or not bool(freshness.get("ready", False))
    )
    if should_rebuild:
        daybook = build_daybook(trade_day, topk=10, reserve_count=2)
        save_daybook(daybook)
    return daybook


def _slot_text(value: str | None) -> str:
    return str(value or "")


def _intraday_runtime_enabled() -> bool:
    return bool(getattr(load_config(), "intraday_runtime_enabled", False))


def _intraday_runtime_disabled_message() -> str:
    return "当前配置已关闭盘中 5 分钟接入，仅保留日级计划与观察状态。"


def _needs_preopen_refresh(current: LiveSlotArtifact | None, *, trade_day: str, market_phase: str, force: bool) -> bool:
    if force or current is None:
        return True
    if current.trade_day != trade_day or current.daybook_effective_day != trade_day:
        return True
    if current.slot_at is not None:
        return True
    if current.market_phase != market_phase:
        return True
    return current.slot_status != "UNAVAILABLE"


def _needs_target_slot_rebuild(
    current: LiveSlotArtifact | None,
    *,
    trade_day: str,
    target_slot_at: str,
    market_phase: str,
    force: bool,
) -> bool:
    if force or current is None:
        return True
    if current.trade_day != trade_day or current.daybook_effective_day != trade_day:
        return True
    current_slot = _slot_text(current.slot_at)
    if not current_slot:
        return True
    if current_slot < target_slot_at:
        return True
    if current_slot == target_slot_at and current.market_phase != market_phase:
        return True
    return current_slot == target_slot_at and current.slot_status == "UNAVAILABLE"


def _needs_intraday_disabled_refresh(
    current: LiveSlotArtifact | None,
    *,
    trade_day: str,
    target_slot_at: str,
    market_phase: str,
    force: bool,
) -> bool:
    if force or current is None:
        return True
    if current.trade_day != trade_day or current.daybook_effective_day != trade_day:
        return True
    if _slot_text(current.slot_at) != target_slot_at:
        return True
    if current.market_phase != market_phase:
        return True
    if current.slot_status != "UNAVAILABLE":
        return True
    reason = str((getattr(current, "provider_meta", {}) or {}).get("reason") or "").strip()
    return reason != INTRADAY_RUNTIME_DISABLED_REASON


def _build_slot_artifact_from_bundle(
    *,
    daybook: DayBook,
    tracked_universe: TrackedUniverse,
    trade_day: str,
    slot_at: str,
    market_phase: str,
    bundle: Dict[str, Any],
    slot_baselines: Dict[str, Dict[str, float]],
    portfolio_snapshot: Dict[str, Any],
    previous_artifact: LiveSlotArtifact | None,
    snapshot_for_slot,
) -> LiveSlotArtifact:
    previous_actions = {}
    previous_states = {}
    if previous_artifact is not None:
        previous_actions = {symbol: pulse.action for symbol, pulse in previous_artifact.symbol_states.items()}
        previous_states = {symbol: pulse.execution_state for symbol, pulse in previous_artifact.symbol_states.items()}

    bars_by_symbol = {
        symbol: df[df["trade_time"] <= pd.to_datetime(slot_at)].reset_index(drop=True)
        for symbol, df in (bundle.get("bars") or {}).items()
    }
    benchmark_full = bundle.get("benchmark")
    benchmark = None
    if benchmark_full is not None and not benchmark_full.empty:
        benchmark = benchmark_full[benchmark_full["trade_time"] <= pd.to_datetime(slot_at)].reset_index(drop=True)
    snapshot = snapshot_for_slot
    breadth_source = "provider_snapshot"
    if snapshot is None or snapshot.empty:
        snapshot = build_slot_breadth_snapshot(bars_by_symbol, slot_at=slot_at)
        if snapshot is not None and not snapshot.empty:
            breadth_source = "derived_from_5m_bars"
    complete = (
        len(bars_by_symbol) == len(tracked_universe.total)
        and benchmark is not None
        and not benchmark.empty
        and snapshot is not None
        and not snapshot.empty
    )
    provisional_pulses = evaluate_slot_pulses(
        daybook=daybook,
        tracked_universe=tracked_universe,
        bars=bars_by_symbol,
        benchmark=benchmark,
        slot_baselines=slot_baselines,
        gate=SlotGate(state="ALLOW", score=100.0, reasons=["pre_gate"]),
        slot_at=slot_at,
        trade_day=trade_day,
        provider=str(bundle.get("provider") or "akshare"),
        previous_actions=previous_actions,
    )
    gate = score_intraday_gate(
        snapshot=snapshot,
        benchmark=benchmark,
        pulses=provisional_pulses,
        tracked_universe=tracked_universe,
        data_complete=complete,
    )
    pulses = evaluate_slot_pulses(
        daybook=daybook,
        tracked_universe=tracked_universe,
        bars=bars_by_symbol,
        benchmark=benchmark,
        slot_baselines=slot_baselines,
        gate=gate,
        slot_at=slot_at,
        trade_day=trade_day,
        provider=str(bundle.get("provider") or "akshare"),
        previous_actions=previous_actions,
    )
    slot_status = "OK" if complete else "DEGRADED"
    if slot_status != "OK":
        for pulse in pulses.values():
            pulse.can_open = False
            pulse.reason_codes = [*pulse.reason_codes, "slot_degraded"]
    artifact_id = gen_id("slot")
    slot_id = slot_id_for(slot_at)
    board = build_board(daybook, pulses, artifact_id=artifact_id, slot_id=slot_id)
    data_quality = SlotDataQuality(
        snapshot_age_sec=(None if snapshot is None or snapshot.empty else bundle.get("snapshot_age_sec")),
        symbols_expected=len(tracked_universe.total),
        symbols_received=len([symbol for symbol, df in bars_by_symbol.items() if df is not None and not df.empty]),
        benchmark_received=bool(benchmark is not None and not benchmark.empty),
        provider=str(bundle.get("provider") or "akshare"),
        complete=complete,
        errors=list(bundle.get("errors") or []),
    )
    artifact = LiveSlotArtifact(
        artifact_id=artifact_id,
        slot_id=slot_id,
        trade_day=trade_day,
        slot_at=slot_at,
        market_phase=market_phase,
        slot_status=slot_status,
        publish_allowed=(slot_status == "OK" and gate.state == "ALLOW"),
        daybook_effective_day=daybook.trading_day,
        gate=gate,
        tracked_universe=tracked_universe,
        board=board,
        symbol_states=pulses,
        data_quality=data_quality,
        portfolio_snapshot=portfolio_snapshot,
        provider_meta={
            "benchmark_symbol": bundle.get("benchmark_symbol"),
            "breadth_source": breadth_source,
        },
        side_results=detect_side_results(previous_states, board),
        created_at=now_iso(),
        updated_at=now_iso(),
    )
    return artifact


def _save_intraday_disabled_artifact(
    *,
    daybook: DayBook,
    trade_day: str,
    target_slot: str,
    market_phase: str,
    freshness: Dict[str, Any],
    force: bool = False,
) -> Dict[str, Any]:
    portfolio_snapshot = load_portfolio_snapshot()
    tracked = _tracked_universe(daybook, portfolio_snapshot)
    current = load_current_slot_artifact()
    if not _needs_intraday_disabled_refresh(
        current,
        trade_day=trade_day,
        target_slot_at=target_slot,
        market_phase=market_phase,
        force=force,
    ):
        return {
            "trade_day": trade_day,
            "artifact_id": current.artifact_id,
            "slot_at": current.slot_at,
            "slot_status": current.slot_status,
            "tracked_total": len(current.tracked_universe.total),
            "market_phase": market_phase,
            "daily_freshness": freshness,
            "disabled": True,
            "reason": INTRADAY_RUNTIME_DISABLED_REASON,
            "message": _intraday_runtime_disabled_message(),
            "noop": True,
        }
    artifact = build_unavailable_artifact(
        daybook=daybook,
        tracked_universe=tracked,
        market_phase=market_phase,
        trade_day=trade_day,
        slot_at=target_slot,
        portfolio_snapshot=portfolio_snapshot,
        reason=INTRADAY_RUNTIME_DISABLED_REASON,
        previous_artifact=current,
    )
    saved = _save_artifact(daybook, artifact)
    saved.update(
        {
            "trade_day": trade_day,
            "tracked_total": len(tracked.total),
            "market_phase": market_phase,
            "daily_freshness": freshness,
            "disabled": True,
            "reason": INTRADAY_RUNTIME_DISABLED_REASON,
            "message": _intraday_runtime_disabled_message(),
        }
    )
    return saved


def run_preopen_init(*, now=None, force: bool = False) -> Dict[str, Any]:
    ms = compute_market_state(now)
    trade_day = ms.target_daybook_effective_day
    daybook = build_daybook(trade_day, topk=10, reserve_count=2)
    freshness = dict(daybook.source_meta.get("daily_freshness") or {})
    if not freshness and daybook_symbols(daybook):
        freshness = reconcile_daily_freshness(daybook_symbols(daybook), as_of=trade_day, strict=True)
        daybook.source_meta["daily_freshness"] = freshness
    portfolio_snapshot = load_portfolio_snapshot()
    tracked = _tracked_universe(daybook, portfolio_snapshot)
    load_slot_volume_baselines(trade_day, tracked.total)
    current = load_current_slot_artifact()
    if not _needs_preopen_refresh(current, trade_day=trade_day, market_phase=ms.market_phase, force=force):
        return {
            "trade_day": trade_day,
            "artifact_id": current.artifact_id,
            "slot_status": current.slot_status,
            "tracked_total": len(current.tracked_universe.total),
            "market_phase": ms.market_phase,
            "noop": True,
        }
    artifact = build_unavailable_artifact(
        daybook=daybook,
        tracked_universe=tracked,
        market_phase=ms.market_phase,
        trade_day=trade_day,
        slot_at=None,
        portfolio_snapshot=portfolio_snapshot,
        reason="preopen_init",
        previous_artifact=current,
    )
    saved = _save_artifact(daybook, artifact)
    saved.update(
        {
            "trade_day": trade_day,
            "tracked_total": len(tracked.total),
            "market_phase": ms.market_phase,
            "daily_freshness": freshness,
            "blocked": bool(freshness and not freshness.get("ready", True)),
        }
    )
    return saved


def boot_replay_to_current_slot(*, now=None, force: bool = False) -> Dict[str, Any]:
    ms = compute_market_state(now)
    trade_day = ms.target_daybook_effective_day
    target_slot = ms.target_pulse_slot_at
    if not target_slot:
        return run_preopen_init(now=now, force=force)
    daybook = _load_or_build_daybook(trade_day)
    freshness = dict(daybook.source_meta.get("daily_freshness") or {})
    if freshness and not bool(freshness.get("ready", True)):
        return {
            "trade_day": trade_day,
            "market_phase": ms.market_phase,
            "blocked": True,
            "reason": "daily_freshness_blocked",
            "daily_freshness": freshness,
            "message": freshness.get("blocking_reason") or "日线数据未补齐到目标交易日，先不回放盘中 5 分钟执行态。",
        }
    if not _intraday_runtime_enabled():
        return _save_intraday_disabled_artifact(
            daybook=daybook,
            trade_day=trade_day,
            target_slot=target_slot,
            market_phase=ms.market_phase,
            freshness=freshness,
            force=force,
        )
    portfolio_snapshot = load_portfolio_snapshot()
    tracked = _tracked_universe(daybook, portfolio_snapshot)
    slot_baselines = load_slot_volume_baselines(trade_day, tracked.total)
    bundle = fetch_intraday_bundle(
        trading_day=trade_day,
        slot_at=target_slot,
        symbols=tracked.total,
        benchmark_symbol=getattr(load_config(), "intraday_benchmark_symbol", "000300"),
    )
    current = load_current_slot_artifact()
    start_from = None
    rebuild_current_slot = _needs_target_slot_rebuild(
        current,
        trade_day=trade_day,
        target_slot_at=target_slot,
        market_phase=ms.market_phase,
        force=force,
    )
    if current is not None and current.trade_day == trade_day:
        start_from = current.slot_at
    slots = iter_trade_slots(trade_day, up_to=target_slot)
    if rebuild_current_slot and start_from and _slot_text(start_from) == _slot_text(target_slot):
        slots = [slot for slot in slots if slot.strftime("%Y-%m-%d %H:%M:%S") == str(target_slot)]
    elif start_from:
        slots = [slot for slot in slots if slot.strftime("%Y-%m-%d %H:%M:%S") > str(start_from)]
    if not slots:
        return {
            "trade_day": trade_day,
            "slot_at": target_slot,
            "artifact_id": current.artifact_id if current else None,
            "slot_status": current.slot_status if current else "UNAVAILABLE",
            "market_phase": ms.market_phase,
            "noop": True,
        }
    built: list[dict[str, Any]] = []
    previous = current
    latest_slot = slots[-1].strftime("%Y-%m-%d %H:%M:%S")
    for slot_dt in slots:
        slot_at = slot_dt.strftime("%Y-%m-%d %H:%M:%S")
        snapshot_for_slot = bundle.get("snapshot") if slot_at == latest_slot else None
        artifact = _build_slot_artifact_from_bundle(
            daybook=daybook,
            tracked_universe=tracked,
            trade_day=trade_day,
            slot_at=slot_at,
            market_phase=ms.market_phase,
            bundle=bundle,
            slot_baselines=slot_baselines,
            portfolio_snapshot=portfolio_snapshot,
            previous_artifact=previous,
            snapshot_for_slot=snapshot_for_slot,
        )
        built.append(_save_artifact(daybook, artifact))
        previous = artifact
    return {
        "trade_day": trade_day,
        "replayed_slots": len(built),
        "market_phase": ms.market_phase,
        "current": built[-1] if built else {},
    }


def replay_today_once() -> Dict[str, Any]:
    return boot_replay_to_current_slot()


def run_postclose_archive(*, now=None, force: bool = False) -> Dict[str, Any]:
    ms = compute_market_state(now)
    daybook = _load_or_build_daybook(ms.target_daybook_effective_day)
    freshness = dict(daybook.source_meta.get("daily_freshness") or {})
    if freshness and not bool(freshness.get("ready", True)):
        return {
            "trade_day": ms.target_daybook_effective_day,
            "market_phase": ms.market_phase,
            "archived": False,
            "blocked": True,
            "reason": "daily_freshness_blocked",
            "daily_freshness": freshness,
            "message": freshness.get("blocking_reason") or "日线数据未补齐到目标交易日，当前不执行收盘归档。",
        }
    replay_result = None
    if ms.target_pulse_slot_at:
        if not _intraday_runtime_enabled():
            replay_result = _save_intraday_disabled_artifact(
                daybook=daybook,
                trade_day=ms.target_daybook_effective_day,
                target_slot=ms.target_pulse_slot_at,
                market_phase=ms.market_phase,
                freshness=freshness,
                force=force,
            )
        else:
            current = load_current_slot_artifact()
            if _needs_target_slot_rebuild(
                current,
                trade_day=ms.target_daybook_effective_day,
                target_slot_at=ms.target_pulse_slot_at,
                market_phase=ms.market_phase,
                force=force,
            ):
                replay_result = boot_replay_to_current_slot(now=now, force=True)
    current = load_current_slot_artifact()
    if current is None:
        return {"trade_day": ms.target_daybook_effective_day, "archived": False, "reason": "no_current_artifact"}
    return {
        "trade_day": current.trade_day,
        "artifact_id": current.artifact_id,
        "slot_id": current.slot_id,
        "slot_status": current.slot_status,
        "market_phase": ms.market_phase,
        "reconciled": replay_result,
        "archived": True,
    }


def reconcile_runtime_state(*, now=None, operation: str = "auto") -> Dict[str, Any]:
    with book_lane():
        ms = compute_market_state(now)
        if operation == "rebuild_daybook":
            result = run_preopen_init(now=now, force=True)
        elif operation == "replay_today":
            result = boot_replay_to_current_slot(now=now, force=True)
        elif operation == "postclose_archive":
            result = run_postclose_archive(now=now, force=True)
        elif ms.market_phase in {PHASE_PREOPEN, PHASE_OPEN_NO_FIRST_BAR}:
            result = run_preopen_init(now=now)
        elif ms.market_phase in {PHASE_INTRADAY_AM, PHASE_INTRADAY_PM, PHASE_LUNCH_BREAK, PHASE_CLOSING_AUCTION}:
            result = boot_replay_to_current_slot(now=now)
        elif ms.market_phase == PHASE_POSTCLOSE_PENDING:
            result = run_postclose_archive(now=now)
        else:
            result = {
                "trade_day": ms.target_daybook_effective_day,
                "market_phase": ms.market_phase,
                "noop": True,
                "reason": "non_trading",
            }
        result.setdefault("market_phase", ms.market_phase)
        result.setdefault("operation", operation)
        return result


def run_pulse_loop() -> Dict[str, Any]:
    cfg = load_config()
    poll = max(5, int(getattr(cfg, "intraday_poll_interval_sec", 15) or 15))
    while True:
        try:
            reconcile_runtime_state()
        except Exception as ex:  # noqa: BLE001
            logger.exception("[worker] pulse loop iteration failed: %s", ex)
        time.sleep(poll)


__all__ = [
    "boot_replay_to_current_slot",
    "replay_today_once",
    "reconcile_runtime_state",
    "run_postclose_archive",
    "run_preopen_init",
    "run_pulse_loop",
]
