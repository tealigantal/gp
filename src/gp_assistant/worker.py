from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import time
from typing import Any, Dict

from .book.board import build_board
from .book.daybook import build_daybook
from .book.pulse5m import compute_slot_pulse_package
from .book.readonly import build_daily_plan_artifact, tracked_universe_from_daybook
from .agent_store import AgentStore
from .book.side_results import detect_side_results
from .contracts.objects import DayBook, LiveSlotArtifact, SlotDataQuality, SlotGate, TrackedUniverse
from .contracts.runtime import RuntimeOperation, require_runtime_operation
from .core.config import load_config
from .core.logging import logger
from .evidence.daily_freshness import (
    TARGET_CURRENT_PENDING,
    TARGET_CURRENT_READY,
    daily_freshness_target_fields,
    daybook_symbols,
    reconcile_daily_freshness,
    resolve_daily_target,
)
from .evidence.market_service import refresh_intraday_min5_cache
from .runtime.lanes import book_lane
from .runtime.market_clock import (
    PHASE_CLOSING_AUCTION,
    PHASE_INTRADAY_AM,
    PHASE_INTRADAY_PM,
    PHASE_LUNCH_BREAK,
    PHASE_OPEN_NO_FIRST_BAR,
    PHASE_POSTCLOSE_PENDING,
    compute_market_state,
)
from .runtime.slot_state import (
    DAILY_EOD_PENDING,
    DAILY_FRESHNESS_BLOCKED,
    DAILY_RECONCILING,
    daily_data_state_from_freshness,
)
from .runtime.utils import gen_id, now_iso
from .runtime.producer import producer_is_compatible, producer_metadata
from .runtime.market_time import MarketTimeContext, compare_snapshot_market_time
from .runtime.native_snapshot import serenity_runtime_binding_check
from .serenity.store import (
    current_native_readiness_state,
)


_INTRADAY_PHASES = {
    PHASE_OPEN_NO_FIRST_BAR,
    PHASE_INTRADAY_AM,
    PHASE_LUNCH_BREAK,
    PHASE_INTRADAY_PM,
    PHASE_CLOSING_AUCTION,
}

_INTRADAY_REFRESH_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gp-min5-refresh")
_INTRADAY_REFRESH_FUTURE: Future | None = None
_INTRADAY_REFRESH_LAST_RESULT: Dict[str, Any] | None = None


def _tracked_universe(daybook: DayBook) -> TrackedUniverse:
    tracked = tracked_universe_from_daybook(daybook)
    tracked.portfolio = []
    return tracked


def _trade_day_iso(trade_day: Any) -> str:
    raw = str(trade_day or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return raw


def _save_artifact(daybook: DayBook, artifact: LiveSlotArtifact, *, market_time: MarketTimeContext) -> Dict[str, Any]:
    if daybook.trading_day != artifact.daybook_effective_day:
        raise RuntimeError("runtime_artifact_trade_day_mismatch")
    if not producer_is_compatible(daybook.producer) or not producer_is_compatible(artifact.producer):
        raise RuntimeError("runtime_artifact_producer_incompatible")
    daybook_symbols_set = {pick.symbol for pick in [*daybook.picks, *daybook.reserve_picks]}
    if any(entry.symbol not in daybook_symbols_set for entry in artifact.board):
        raise RuntimeError("runtime_artifact_board_outside_daybook")
    AgentStore().publish_runtime_artifact(daybook, artifact, market_time=market_time)
    return {
        "artifact_id": artifact.artifact_id,
        "slot_id": artifact.slot_id,
        "slot_at": artifact.slot_at,
        "slot_status": artifact.slot_status,
        "gate": artifact.gate.state,
        "publish_allowed": artifact.publish_allowed,
    }


def _load_or_build_daybook(market_time: MarketTimeContext, *, force: bool = False) -> DayBook:
    """Reuse an immutable, producer-compatible daybook for completed bars only."""
    store = AgentStore()
    daybook = None if force else store.load_daybook(market_time.daybook_effective_day, producer=producer_metadata())
    if daybook is not None:
        candidate_universe = dict(daybook.source_meta.get("candidate_universe") or {})
        if (
            str(candidate_universe.get("schema") or "")
            != "MarketUniverseSnapshot.v1"
            or candidate_universe.get("complete") is not True
        ):
            daybook = None
    if daybook is not None and daybook.source_meta.get("serenity_native_ready") is False:
        target_id = str(daybook.source_meta.get("serenity_target_id") or "")
        if not target_id:
            daybook = None
        else:
            try:
                current = current_native_readiness_state(
                    target_id, decision_at=market_time.observed_at
                )
            except Exception:
                current = {}
            if (
                not bool(current.get("target_matches"))
                or bool(current.get("certificate_current"))
            ):
                daybook = None
    if daybook is not None and daybook.source_meta.get("serenity_native_ready") is True:
        source_meta = dict(daybook.source_meta or {})
        target_id = str(daybook.source_meta.get("serenity_target_id") or "")
        try:
            current = current_native_readiness_state(
                target_id, decision_at=market_time.observed_at
            )
        except Exception:
            current = {}
        serenity_reason, _ = serenity_runtime_binding_check(
            source_meta, current
        )
        if serenity_reason:
            daybook = None
    if daybook is not None and producer_is_compatible(daybook.producer):
        return daybook
    daybook = build_daybook(
        market_time.daybook_effective_ymd,
        topk=10,
        reserve_count=2,
        decision_trade_day=market_time.decision_trade_day,
        observed_at=market_time.observed_at,
    )
    if _trade_day_iso(daybook.trading_day) != market_time.daybook_effective_day:
        raise RuntimeError("daybook_effective_day_mismatch")
    daybook.source_meta["market_time"] = market_time.as_dict()
    return daybook


def _snapshot_contains_daybook(snapshot: Any, daybook: DayBook) -> bool:
    """Return whether the current pointer already publishes this exact DayBook."""

    if snapshot is None:
        return False
    try:
        published = AgentStore.book_for_snapshot(snapshot).daybook
    except Exception:
        return False
    return published.model_dump(mode="json") == daybook.model_dump(mode="json")


def _snapshot_matches_market_time(
    snapshot: Any, market_time: MarketTimeContext
) -> bool:
    return bool(
        snapshot is not None
        and compare_snapshot_market_time(snapshot, market_time).get("matches")
    )


_DAILY_PLAN_META_KEYS = (
    "daybook_generated_at",
    "daily_target_day",
    "daily_target_mode",
    "daily_last_reconcile_at",
    "market_phase",
)


def _daily_last_reconcile_at(freshness: Dict[str, Any]) -> Any:
    return freshness.get("last_reconcile_at") or freshness.get("generated_at") or freshness.get("reconciled_at")


def _daily_plan_publish_meta(daybook: DayBook, *, market_phase: str) -> Dict[str, Any]:
    freshness = dict(getattr(daybook, "source_meta", {}).get("daily_freshness") or {})
    return {
        "daybook_generated_at": getattr(daybook, "generated_at", None),
        "daily_target_day": freshness.get("target_day"),
        "daily_target_mode": freshness.get("target_mode"),
        "daily_last_reconcile_at": _daily_last_reconcile_at(freshness),
        "market_phase": market_phase,
    }


def _daily_plan_meta_matches(provider_meta: Dict[str, Any], expected_meta: Dict[str, Any]) -> bool:
    return all(key in provider_meta and provider_meta.get(key) == expected_meta.get(key) for key in _DAILY_PLAN_META_KEYS)


def _schedule_intraday_min5_refresh(**kwargs: Any) -> Dict[str, Any]:
    global _INTRADAY_REFRESH_FUTURE, _INTRADAY_REFRESH_LAST_RESULT

    if _INTRADAY_REFRESH_FUTURE is not None and _INTRADAY_REFRESH_FUTURE.done():
        try:
            _INTRADAY_REFRESH_LAST_RESULT = dict(_INTRADAY_REFRESH_FUTURE.result() or {})
        except Exception as ex:  # noqa: BLE001
            _INTRADAY_REFRESH_LAST_RESULT = {"skipped": False, "reason": "background_refresh_failed", "error": f"{type(ex).__name__}: {ex}"}
        _INTRADAY_REFRESH_FUTURE = None

    if _INTRADAY_REFRESH_FUTURE is not None:
        return {
            "scheduled": False,
            "running": True,
            "reason": "refresh_already_running",
            "last_result": _INTRADAY_REFRESH_LAST_RESULT,
        }

    _INTRADAY_REFRESH_FUTURE = _INTRADAY_REFRESH_EXECUTOR.submit(refresh_intraday_min5_cache, **kwargs)
    return {
        "scheduled": True,
        "running": True,
        "reason": "background_refresh_started",
        "last_result": _INTRADAY_REFRESH_LAST_RESULT,
    }


def _refresh_elapsed_sec(refresh_report: Dict[str, Any] | None) -> Any:
    if not refresh_report:
        return None
    if "elapsed_sec" in refresh_report:
        return refresh_report.get("elapsed_sec")
    last_result = refresh_report.get("last_result")
    if isinstance(last_result, dict):
        return last_result.get("elapsed_sec")
    return None


def _build_and_save_daily_plan(*, daybook: DayBook, trade_day: str, market_phase: str, market_time: MarketTimeContext | None = None, force: bool = False) -> Dict[str, Any]:
    return _build_and_save_runtime_artifact(
        daybook=daybook,
        trade_day=trade_day,
        market_phase=market_phase,
        target_slot_at=None,
        enable_minutes=False,
        market_time=market_time,
        force=force,
    )


def _build_and_save_runtime_artifact(
    *,
    daybook: DayBook,
    trade_day: str,
    market_phase: str,
    target_slot_at: str | None,
    enable_minutes: bool,
    market_time: MarketTimeContext | None = None,
    force: bool = False,
) -> Dict[str, Any]:
    portfolio_snapshot: Dict[str, Any] = {}
    tracked = _tracked_universe(daybook)
    current = None
    expected_meta = _daily_plan_publish_meta(daybook, market_phase=market_phase)
    runtime_stage = "minute" if enable_minutes and target_slot_at else "daily"
    expected_runtime_meta = {
        **expected_meta,
        "chain": "runtime",
        "runtime_stage": runtime_stage,
    }
    if (
        not force
        and current is not None
        and current.trade_day == trade_day
        and current.daybook_effective_day == daybook.trading_day
        and current.slot_status == "OK"
        and current.provider_meta.get("chain") == "runtime"
        and current.provider_meta.get("runtime_stage") == runtime_stage
        and (current.slot_at or None) == (target_slot_at if runtime_stage == "minute" else None)
        and _daily_plan_meta_matches(current.provider_meta, expected_meta)
        and producer_is_compatible(current.producer)
    ):
        return {
            "trade_day": trade_day,
            "artifact_id": current.artifact_id,
            "slot_id": current.slot_id,
            "slot_at": current.slot_at,
            "slot_status": current.slot_status,
            "tracked_total": len(current.tracked_universe.total),
            "market_phase": market_phase,
            "runtime_chain": True,
            "runtime_stage": runtime_stage,
            "daily_plan_only": runtime_stage != "minute",
            "intraday_pulse": runtime_stage == "minute",
            "noop": True,
        }
    if runtime_stage == "minute":
        previous_actions = {
            symbol: pulse.execution_state
            for symbol, pulse in ((current.symbol_states or {}).items() if current is not None else [])
        }
        cfg = load_config()
        core_symbols = [*tracked.reco, *tracked.portfolio]
        refresh_report = _schedule_intraday_min5_refresh(
            trading_day=trade_day,
            slot_at=target_slot_at,
            symbols=tracked.total,
            benchmark_symbol=getattr(cfg, "intraday_benchmark_symbol", "000300"),
            core_symbols=core_symbols,
            force=force,
        )
        try:
            pkg = compute_slot_pulse_package(
                daybook=daybook,
                tracked_universe=tracked,
                trade_day=trade_day,
                slot_at=target_slot_at,
                previous_actions=previous_actions,
                benchmark_symbol=getattr(cfg, "intraday_benchmark_symbol", "000300"),
            )
        except Exception as ex:  # noqa: BLE001
            logger.warning("[worker] intraday pulse degraded trade_day=%s slot=%s error=%s", trade_day, target_slot_at, ex)
            pkg = {
                "pulses": {},
                "gate": SlotGate(state="UNAVAILABLE", score=0.0, reasons=["intraday_pulse_failed"]),
                "bundle": {
                    "errors": [f"{type(ex).__name__}: {ex}"],
                    "snapshot_age_sec": None,
                    "symbols_expected": len(tracked.total),
                    "symbols_received": 0,
                    "benchmark_received": False,
                    "provider": "akshare",
                },
            }
        bundle = dict(pkg.get("bundle") or {})
        pulses = dict(pkg.get("pulses") or {})
        gate = pkg["gate"]
        errors = list(bundle.get("errors") or [])
        legacy_complete = (
            int(bundle.get("symbols_received") or 0) == int(bundle.get("symbols_expected") or 0)
            and bool(bundle.get("benchmark_received"))
            and not errors
        )
        complete = (bool(bundle.get("model_usable")) if "model_usable" in bundle else legacy_complete) and bool(bundle.get("benchmark_received")) and not errors
        slot_status = "OK" if complete else "DEGRADED"
        artifact_id = gen_id("slot")
        effective_slot_at = str(bundle.get("effective_slot_at") or target_slot_at)
        slot_id = _slot_id(effective_slot_at)
        board = build_board(daybook, pulses, artifact_id=artifact_id, slot_id=slot_id)
        old_map = {symbol: pulse.execution_state for symbol, pulse in ((current.symbol_states or {}).items() if current is not None else [])}
        now = now_iso()
        artifact = LiveSlotArtifact(
            artifact_id=artifact_id,
            slot_id=slot_id,
            trade_day=trade_day,
            slot_at=effective_slot_at,
            market_phase=market_phase,
            slot_status=slot_status,
            publish_allowed=bool(daybook.tradeable and str(getattr(gate, "state", "")).upper() == "ALLOW"),
            daybook_effective_day=daybook.trading_day,
            gate=gate,
            tracked_universe=tracked,
            board=board,
            symbol_states=pulses,
            data_quality=SlotDataQuality(
                snapshot_age_sec=bundle.get("snapshot_age_sec"),
                symbols_expected=int(bundle.get("symbols_expected") or len(tracked.total)),
                symbols_received=int(bundle.get("symbols_received") or len(pulses)),
                benchmark_received=bool(bundle.get("benchmark_received")),
                provider=str(bundle.get("provider") or "akshare"),
                complete=bool(complete),
                errors=errors,
                target_slot_at=str(bundle.get("target_slot_at") or target_slot_at),
                effective_slot_at=effective_slot_at,
                freshness_state=str(bundle.get("freshness_state") or ("fresh" if complete else "degraded")),
                data_age_sec=bundle.get("data_age_sec"),
                fresh_symbols=list(bundle.get("fresh_symbols") or []),
                usable_stale_symbols=list(bundle.get("usable_stale_symbols") or []),
                missing_symbols=list(bundle.get("missing_symbols") or []),
                fetch_elapsed_sec=_refresh_elapsed_sec(refresh_report),
                cache_hit_rate=bundle.get("cache_hit_rate"),
            ),
            portfolio_snapshot=portfolio_snapshot,
            provider_meta={
                **expected_runtime_meta,
                "reason": "intraday_pulse",
                "data_status": "ok" if complete else "degraded",
                "refresh_report": refresh_report,
            },
            side_results=detect_side_results(old_map, board),
            created_at=now,
            updated_at=now,
            producer=producer_metadata(),
        )
    else:
        artifact = build_daily_plan_artifact(
            daybook=daybook,
            tracked_universe=tracked,
            market_phase=market_phase,
            trade_day=trade_day,
            portfolio_snapshot=portfolio_snapshot,
            previous_artifact=current,
        )
        artifact.provider_meta.update(
            {
                **expected_runtime_meta,
                "reason": "daily_plan",
                "data_status": "daily_plan",
            }
        )
    if market_time is None:
        market_time = resolve_daily_target(trade_day)
    saved = _save_artifact(daybook, artifact, market_time=market_time)
    saved.update(
        {
            "trade_day": trade_day,
            "tracked_total": len(tracked.total),
            "market_phase": market_phase,
            "runtime_chain": True,
            "runtime_stage": runtime_stage,
            "daily_plan_only": runtime_stage != "minute",
            "intraday_pulse": runtime_stage == "minute",
        }
    )
    return saved


def _slot_id(slot_at: str | None) -> str | None:
    if not slot_at:
        return None
    return "".join(ch for ch in str(slot_at) if ch.isdigit())[:12] or None


def _runtime_capabilities(cfg, ms, *, operation: RuntimeOperation) -> Dict[str, bool]:
    minutes_enabled = (
        operation == "auto"
        and bool(getattr(cfg, "intraday_runtime_enabled", False))
        and ms.market_phase in _INTRADAY_PHASES
        and bool(ms.target_pulse_slot_at)
    )
    return {
        "daily": True,
        "minutes": minutes_enabled,
        "portfolio": False,
    }


def run_runtime_chain(*, now=None, operation: RuntimeOperation | str = "auto") -> Dict[str, Any]:
    operation = require_runtime_operation(operation)
    cfg = load_config()
    ms = compute_market_state(now)
    market_time = resolve_daily_target(now=now)
    force_daybook = operation in {"rebuild_daybook", "postclose_archive"}
    if market_time.target_mode == TARGET_CURRENT_PENDING:
        return {
            "trade_day": market_time.decision_trade_ymd,
            "decision_trade_day": market_time.decision_trade_day,
            "daybook_effective_day": market_time.daybook_effective_day,
            "market_phase": ms.market_phase,
            "operation": operation,
            "runtime_chain": True,
            "runtime_stage": "probing_eod",
            "archived": False,
            "pending": True,
            "reason": "eod_daily_pending",
            "daily_data_state": DAILY_EOD_PENDING,
            "daily_status": DAILY_EOD_PENDING,
            "daily_freshness": daily_freshness_target_fields(market_time),
            "daily_plan_only": True,
            "message": "今日收盘日线尚未就绪，后台会按探测 TTL 自动重试。",
        }
    daybook = _load_or_build_daybook(market_time, force=force_daybook)
    freshness = dict(daybook.source_meta.get("daily_freshness") or {})
    if not freshness and daybook_symbols(daybook):
        freshness = reconcile_daily_freshness(daybook_symbols(daybook), as_of=market_time.daybook_effective_day, strict=True)
        daybook.source_meta["daily_freshness"] = freshness
    daily_data_state = daily_data_state_from_freshness(freshness) if freshness else "unavailable"
    if daily_data_state == DAILY_EOD_PENDING:
        if ms.market_phase == PHASE_POSTCLOSE_PENDING or operation == "postclose_archive":
            return {
                "trade_day": ms.target_daybook_effective_day,
                "market_phase": ms.market_phase,
                "operation": operation,
                "runtime_chain": True,
                "runtime_stage": "daily_pending",
                "archived": False,
                "pending": True,
                "reason": "eod_daily_pending",
                "daily_data_state": daily_data_state,
                "daily_status": daily_data_state,
                "daily_freshness": freshness,
                "daily_plan_only": True,
                "message": "今日收盘日线尚未就绪，后台会按探测 TTL 自动重试。",
            }
    if daily_data_state == DAILY_RECONCILING:
        return {
            "trade_day": ms.target_daybook_effective_day,
            "market_phase": ms.market_phase,
            "operation": operation,
            "runtime_chain": True,
            "runtime_stage": "daily_reconciling",
            "pending": True,
            "reason": "daily_reconciling",
            "daily_data_state": daily_data_state,
            "daily_status": daily_data_state,
            "daily_freshness": freshness,
            "daily_plan_only": True,
            "message": "今日收盘日线已进入确认流程，等待 freshness report 完成后再发布。",
        }
    if daily_data_state == DAILY_FRESHNESS_BLOCKED:
        # A full-market coverage failure is itself a publishable, auditable
        # no-trade decision. Publishing it replaces any legacy ten-symbol
        # current pointer while preserving all historical snapshots.
        if freshness.get("universe_id"):
            saved = _build_and_save_daily_plan(
                daybook=daybook,
                trade_day=market_time.decision_trade_ymd,
                market_phase=ms.market_phase,
                market_time=market_time,
                force=force_daybook,
            )
            saved.update(
                {
                    "operation": operation,
                    "blocked": True,
                    "reason": "candidate_universe_incomplete",
                    "daily_freshness": freshness,
                    "daily_data_state": daily_data_state,
                    "daily_status": daily_data_state,
                    "daily_plan_only": True,
                }
            )
            return saved
        return {
            "trade_day": ms.target_daybook_effective_day,
            "market_phase": ms.market_phase,
            "operation": operation,
            "runtime_chain": True,
            "runtime_stage": "daily_blocked",
            "blocked": True,
            "reason": "daily_freshness_blocked",
            "daily_data_state": daily_data_state,
            "daily_status": daily_data_state,
            "daily_freshness": freshness,
            "daily_plan_only": True,
            "message": freshness.get("blocking_reason") or "日线数据未补齐到目标交易日，当前不刷新运行时链路。",
        }

    caps = _runtime_capabilities(cfg, ms, operation=operation)
    current = AgentStore().current_snapshot()
    if (
        not force_daybook and not caps["minutes"]
        and _snapshot_matches_market_time(current, market_time)
        and _snapshot_contains_daybook(current, daybook)
    ):
        return {
            "trade_day": market_time.decision_trade_ymd, "decision_trade_day": market_time.decision_trade_day,
            "daybook_effective_day": market_time.daybook_effective_day, "artifact_id": current.snapshot_id,
            "runtime_chain": True, "runtime_stage": "daily", "daily_plan_only": True, "intraday_pulse": False,
            "noop": True, "operation": operation, "daily_freshness": freshness, "daily_data_state": daily_data_state,
            "daily_status": daily_data_state, "capabilities": caps,
        }
    if caps["minutes"]:
        saved = _build_and_save_runtime_artifact(
            daybook=daybook,
            trade_day=market_time.decision_trade_ymd,
            market_phase=ms.market_phase,
            target_slot_at=ms.target_pulse_slot_at,
            enable_minutes=True,
            market_time=market_time,
            force=force_daybook,
        )
    else:
        saved = _build_and_save_daily_plan(
            daybook=daybook,
            trade_day=market_time.decision_trade_ymd,
            market_phase=ms.market_phase,
            market_time=market_time,
            force=force_daybook,
        )
    saved["operation"] = operation
    saved["daily_freshness"] = freshness
    saved["daily_data_state"] = daily_data_state
    saved["daily_status"] = daily_data_state
    saved["capabilities"] = caps
    if operation == "postclose_archive" or (operation == "auto" and ms.market_phase == PHASE_POSTCLOSE_PENDING):
        saved["archived"] = True
    return saved


def reconcile_runtime_state(*, now=None, operation: RuntimeOperation | str = "auto", lock_timeout_sec: float | None = None) -> Dict[str, Any]:
    operation = require_runtime_operation(operation)
    with book_lane(timeout_sec=lock_timeout_sec):
        result = run_runtime_chain(now=now, operation=operation)
        result.setdefault("daily_plan_only", not bool(result.get("intraday_pulse")))
        return result


def run_runtime_loop() -> Dict[str, Any]:
    cfg = load_config()
    AgentStore().initialize()
    poll = max(30, int(getattr(cfg, "intraday_poll_interval_sec", 60) or 60))
    while True:
        try:
            result = reconcile_runtime_state()
            logger.info(
                "[worker] runtime loop completed stage=%s noop=%s trade_day=%s artifact_id=%s",
                result.get("runtime_stage"),
                bool(result.get("noop")),
                result.get("trade_day"),
                result.get("artifact_id"),
            )
        except Exception as ex:  # noqa: BLE001
            logger.exception("[worker] runtime loop iteration failed: %s", ex)
        time.sleep(poll)
__all__ = [
    "reconcile_runtime_state",
    "run_runtime_chain",
    "run_runtime_loop",
]
