from __future__ import annotations

import time
from typing import Any, Dict

from .book.daybook import build_daybook
from .book.readonly import build_daily_plan_artifact, tracked_universe_from_daybook
from .book.repo import (
    compose_market_book,
    load_current_slot_artifact,
    load_daybook,
    save_book,
    save_current_pointer,
    save_daybook,
    save_slot_artifact,
)
from .contracts.objects import CurrentSlotPointer, DayBook, LiveSlotArtifact, TrackedUniverse
from .core.config import load_config
from .core.logging import logger
from .evidence.daily_freshness import TARGET_CURRENT_PENDING, daybook_symbols, reconcile_daily_freshness, resolve_daily_target
from .evidence.portfolio_service import load_portfolio_snapshot
from .runtime.lanes import book_lane
from .runtime.market_clock import compute_market_state


def _portfolio_symbols(snapshot: Dict[str, Any]) -> list[str]:
    return [
        str(item.get("symbol")).strip()
        for item in (snapshot.get("positions") or [])
        if str(item.get("symbol") or "").strip()
    ]


def _tracked_universe(daybook: DayBook, portfolio_snapshot: Dict[str, Any]) -> TrackedUniverse:
    tracked = tracked_universe_from_daybook(daybook)
    holdings = _portfolio_symbols(portfolio_snapshot) if getattr(load_config(), "intraday_include_portfolio", True) else []
    total = list(tracked.total)
    seen = set(total)
    for symbol in holdings:
        if symbol and symbol not in seen:
            seen.add(symbol)
            total.append(symbol)
    tracked.portfolio = holdings
    tracked.total = total
    return tracked


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


def _load_or_build_daybook(trade_day: str, *, force: bool = False) -> DayBook:
    daybook = None if force else load_daybook(trade_day)
    freshness = dict(daybook.source_meta.get("daily_freshness") or {}) if daybook is not None else {}
    target_info = resolve_daily_target(trade_day)
    target_day = str(target_info.get("target_day") or "")
    should_rebuild = (
        daybook is None
        or not freshness
        or freshness.get("target_day") != target_day
        or not bool(freshness.get("ready", False))
    )
    if should_rebuild:
        daybook = build_daybook(trade_day, topk=10, reserve_count=2)
        save_daybook(daybook)
    return daybook


def _build_and_save_daily_plan(*, daybook: DayBook, trade_day: str, market_phase: str, force: bool = False) -> Dict[str, Any]:
    portfolio_snapshot = load_portfolio_snapshot()
    tracked = _tracked_universe(daybook, portfolio_snapshot)
    current = load_current_slot_artifact()
    if (
        not force
        and current is not None
        and current.trade_day == trade_day
        and current.daybook_effective_day == daybook.trading_day
        and current.slot_status == "OK"
        and current.provider_meta.get("reason") == "daily_plan"
    ):
        return {
            "trade_day": trade_day,
            "artifact_id": current.artifact_id,
            "slot_status": current.slot_status,
            "tracked_total": len(current.tracked_universe.total),
            "market_phase": market_phase,
            "daily_plan_only": True,
            "noop": True,
        }
    artifact = build_daily_plan_artifact(
        daybook=daybook,
        tracked_universe=tracked,
        market_phase=market_phase,
        trade_day=trade_day,
        portfolio_snapshot=portfolio_snapshot,
        previous_artifact=current,
    )
    saved = _save_artifact(daybook, artifact)
    saved.update(
        {
            "trade_day": trade_day,
            "tracked_total": len(tracked.total),
            "market_phase": market_phase,
            "daily_plan_only": True,
        }
    )
    return saved


def run_preopen_init(*, now=None, force: bool = False) -> Dict[str, Any]:
    ms = compute_market_state(now)
    trade_day = ms.target_daybook_effective_day
    daybook = _load_or_build_daybook(trade_day, force=force)
    freshness = dict(daybook.source_meta.get("daily_freshness") or {})
    if not freshness and daybook_symbols(daybook):
        freshness = reconcile_daily_freshness(daybook_symbols(daybook), as_of=trade_day, strict=True)
        daybook.source_meta["daily_freshness"] = freshness
    if freshness and not bool(freshness.get("ready", True)):
        return {
            "trade_day": trade_day,
            "market_phase": ms.market_phase,
            "blocked": True,
            "reason": "daily_freshness_blocked",
            "daily_freshness": freshness,
            "message": freshness.get("blocking_reason") or "日线数据未补齐到目标交易日，当前不刷新日线计划。",
        }
    saved = _build_and_save_daily_plan(daybook=daybook, trade_day=trade_day, market_phase=ms.market_phase, force=force)
    saved["daily_freshness"] = freshness
    saved["blocked"] = False
    return saved


def boot_replay_to_current_slot(*, now=None, force: bool = False) -> Dict[str, Any]:
    result = run_preopen_init(now=now, force=force)
    result["replay_disabled"] = True
    result.setdefault("message", "本次按日线计划链路处理。")
    return result


def replay_today_once() -> Dict[str, Any]:
    return boot_replay_to_current_slot(force=True)


def run_postclose_archive(*, now=None, force: bool = False) -> Dict[str, Any]:
    ms = compute_market_state(now)
    daybook = _load_or_build_daybook(ms.target_daybook_effective_day, force=force)
    freshness = dict(daybook.source_meta.get("daily_freshness") or {})
    if freshness.get("target_mode") == TARGET_CURRENT_PENDING:
        return {
            "trade_day": ms.target_daybook_effective_day,
            "market_phase": ms.market_phase,
            "archived": False,
            "pending": True,
            "reason": "eod_daily_pending",
            "daily_freshness": freshness,
            "message": "今日收盘日线尚未就绪，后台会按探测 TTL 自动重试。",
        }
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
    saved = _build_and_save_daily_plan(daybook=daybook, trade_day=ms.target_daybook_effective_day, market_phase=ms.market_phase, force=force)
    saved["archived"] = True
    return saved


def reconcile_runtime_state(*, now=None, operation: str = "auto") -> Dict[str, Any]:
    with book_lane():
        ms = compute_market_state(now)
        if operation == "postclose_archive":
            result = run_postclose_archive(now=now, force=True)
        else:
            result = run_preopen_init(now=now, force=(operation in {"rebuild_daybook", "replay_today"}))
        result.setdefault("market_phase", ms.market_phase)
        result.setdefault("operation", operation)
        result.setdefault("daily_plan_only", True)
        return result


def run_daily_loop() -> Dict[str, Any]:
    cfg = load_config()
    poll = max(30, int(getattr(cfg, "intraday_poll_interval_sec", 60) or 60))
    while True:
        try:
            reconcile_runtime_state()
        except Exception as ex:  # noqa: BLE001
            logger.exception("[worker] daily loop iteration failed: %s", ex)
        time.sleep(poll)


__all__ = [
    "boot_replay_to_current_slot",
    "replay_today_once",
    "reconcile_runtime_state",
    "run_daily_loop",
    "run_postclose_archive",
    "run_preopen_init",
]
