from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..evidence.daily_freshness import TARGET_CURRENT_PENDING, TARGET_CURRENT_READY, TARGET_PREVIOUS_COMPLETED
from .market_clock import (
    PHASE_CLOSING_AUCTION,
    PHASE_INTRADAY_AM,
    PHASE_INTRADAY_PM,
    PHASE_LUNCH_BREAK,
    PHASE_NON_TRADING,
    PHASE_OPEN_NO_FIRST_BAR,
    PHASE_POSTCLOSE_PENDING,
    PHASE_PREOPEN,
)


DAILY_PREVIOUS_COMPLETED = "previous_completed"
DAILY_EOD_PENDING = "eod_pending"
DAILY_RECONCILING = "daily_reconciling"
DAILY_FRESHNESS_BLOCKED = "freshness_blocked"
DAILY_READY = "ready"
DAILY_UNAVAILABLE = "unavailable"

ARTIFACT_STAGE_NONE = "none"
ARTIFACT_STAGE_DAILY_PLAN = "daily_plan"
ARTIFACT_STAGE_INTRADAY_PULSE = "intraday_pulse"
ARTIFACT_STAGE_UNKNOWN = "unknown"

ARTIFACT_FRESHNESS_CURRENT = "current"
ARTIFACT_FRESHNESS_LAGGING = "lagging"
ARTIFACT_FRESHNESS_UNAVAILABLE = "unavailable"
ARTIFACT_FRESHNESS_BLOCKED = "blocked"

TRADEABILITY_TRADEABLE = "tradeable"
TRADEABILITY_NO_TRADE = "no_trade"
TRADEABILITY_BLOCKED = "blocked"

_AUTO_UPDATE_PHASES = {
    PHASE_PREOPEN,
    PHASE_OPEN_NO_FIRST_BAR,
    PHASE_INTRADAY_AM,
    PHASE_LUNCH_BREAK,
    PHASE_INTRADAY_PM,
    PHASE_CLOSING_AUCTION,
    PHASE_POSTCLOSE_PENDING,
}

_INTRADAY_SLOT_PHASES = {
    PHASE_OPEN_NO_FIRST_BAR,
    PHASE_INTRADAY_AM,
    PHASE_LUNCH_BREAK,
    PHASE_INTRADAY_PM,
    PHASE_CLOSING_AUCTION,
}

_DAILY_PLAN_META_KEYS = (
    "daybook_generated_at",
    "daily_target_day",
    "daily_target_mode",
    "daily_last_reconcile_at",
    "market_phase",
)


@dataclass(frozen=True)
class RuntimeStateSnapshot:
    market_phase: str
    clock_data_status: str | None
    daily_data_state: str
    daily_runtime: dict[str, Any]
    artifact_stage: str
    artifact_freshness: str
    artifact_lag_reason: str | None = None
    artifact_lag_fields: list[str] = field(default_factory=list)
    book_freshness: str = DAILY_UNAVAILABLE
    tradeability_state: str = TRADEABILITY_BLOCKED
    auto_update_expected: bool = False

    @property
    def daily_status(self) -> str:
        return self.daily_data_state

    @property
    def artifact_status(self) -> str:
        return self.artifact_freshness


def trade_day_iso(trade_day: Any) -> str:
    raw = str(trade_day or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return raw


def daily_last_reconcile_at(freshness: dict[str, Any]) -> Any:
    return freshness.get("last_reconcile_at") or freshness.get("generated_at") or freshness.get("reconciled_at")


def daily_freshness_fields_from_report(freshness: dict[str, Any]) -> dict[str, Any]:
    return {
        "daily_freshness_ready": bool(freshness.get("ready", False)),
        "daily_target_day": freshness.get("target_day") or freshness.get("daily_target_day"),
        "daily_target_mode": freshness.get("target_mode") or freshness.get("daily_target_mode"),
        "pending_eod_day": freshness.get("pending_eod_day"),
        "eod_probe": freshness.get("eod_probe"),
        "daily_checked_count": int(freshness.get("checked_count") or len(freshness.get("checked_symbols") or [])),
        "daily_stale_count": int(freshness.get("stale_count") or len(freshness.get("stale_symbols") or [])),
        "daily_last_reconcile_at": daily_last_reconcile_at(freshness),
        "daily_blocking_reason": freshness.get("blocking_reason") or freshness.get("daily_blocking_reason"),
        "daily_stale_symbols": list(freshness.get("stale_symbols") or freshness.get("daily_stale_symbols") or []),
        "daily_failed_symbols": list(freshness.get("failed_symbols") or freshness.get("daily_failed_symbols") or []),
    }


def daily_freshness_fields_from_book(book: Any) -> dict[str, Any]:
    source_meta = getattr(getattr(book, "daybook", None), "source_meta", {}) or {}
    freshness = dict(source_meta.get("daily_freshness") or {})
    return daily_freshness_fields_from_report(freshness)


def empty_daily_freshness_fields() -> dict[str, Any]:
    return {
        "daily_freshness_ready": False,
        "daily_checked_count": 0,
        "daily_stale_count": 0,
        "daily_last_reconcile_at": None,
        "daily_blocking_reason": None,
        "daily_stale_symbols": [],
        "daily_failed_symbols": [],
    }


def latest_daily_freshness_fields_for_target(target_day: Any, latest_report: dict[str, Any] | None) -> dict[str, Any]:
    target_iso = trade_day_iso(target_day)
    if not target_iso or not latest_report:
        return {}
    if trade_day_iso(latest_report.get("target_day") or latest_report.get("daily_target_day")) != target_iso:
        return {}
    return daily_freshness_fields_from_report(dict(latest_report))


def build_daily_runtime_fields(
    *,
    book: Any,
    market_state: Any,
    daily_target: dict[str, Any],
    latest_freshness_report: dict[str, Any] | None,
    repair_snapshot: Any = None,
) -> dict[str, Any]:
    book_daily_freshness = daily_freshness_fields_from_book(book) if book is not None else {}
    daily_freshness = dict(book_daily_freshness)
    daily_target_day = daily_target.get("target_day") or book_daily_freshness.get("daily_target_day")
    daily_target_mode = daily_target.get("target_mode") or book_daily_freshness.get("daily_target_mode")
    pending_eod_day = (
        daily_target.get("pending_eod_day")
        if "pending_eod_day" in daily_target
        else book_daily_freshness.get("pending_eod_day")
    )
    eod_probe = daily_target.get("eod_probe") if "eod_probe" in daily_target else book_daily_freshness.get("eod_probe")
    source_target_day = book_daily_freshness.get("daily_target_day")
    source_target_mode = book_daily_freshness.get("daily_target_mode")

    if (
        book_daily_freshness.get("daily_freshness_ready") is True
        and str(source_target_mode or "") == TARGET_CURRENT_READY
        and str(source_target_day or "") == trade_day_iso(getattr(market_state, "target_daybook_effective_day", None))
    ):
        daily_target_day = source_target_day
        daily_target_mode = source_target_mode
        pending_eod_day = book_daily_freshness.get("pending_eod_day")
        eod_probe = book_daily_freshness.get("eod_probe")
        daily_freshness = dict(book_daily_freshness)

    if source_target_day and daily_target_day and str(source_target_day) != str(daily_target_day):
        latest_fields = latest_daily_freshness_fields_for_target(daily_target_day, latest_freshness_report)
        daily_freshness = latest_fields or {**book_daily_freshness, **empty_daily_freshness_fields()}
        if latest_fields:
            daily_target_day = latest_fields.get("daily_target_day") or daily_target_day
            daily_target_mode = latest_fields.get("daily_target_mode") or daily_target_mode
            pending_eod_day = latest_fields.get("pending_eod_day")
            eod_probe = latest_fields.get("eod_probe")
    elif daily_target_day:
        latest_fields = latest_daily_freshness_fields_for_target(daily_target_day, latest_freshness_report)
        if latest_fields:
            daily_freshness = latest_fields
            daily_target_day = latest_fields.get("daily_target_day") or daily_target_day
            if str(daily_target_mode or "").lower() == TARGET_CURRENT_PENDING:
                daily_freshness["daily_target_mode"] = TARGET_CURRENT_PENDING
                daily_freshness["pending_eod_day"] = pending_eod_day
                daily_freshness["eod_probe"] = eod_probe
            else:
                daily_target_mode = latest_fields.get("daily_target_mode") or daily_target_mode
                pending_eod_day = latest_fields.get("pending_eod_day")
                eod_probe = latest_fields.get("eod_probe")

    return {
        **daily_freshness,
        "daily_target_day": str(daily_target_day) if daily_target_day else (repair_snapshot.daily_target_day if repair_snapshot else None),
        "daily_target_mode": str(daily_target_mode) if daily_target_mode else None,
        "pending_eod_day": str(pending_eod_day) if pending_eod_day else None,
        "eod_probe": eod_probe if isinstance(eod_probe, dict) else None,
    }


def daily_data_state_from_runtime(daily_runtime: dict[str, Any], *, book_available: bool) -> str:
    if not book_available:
        return DAILY_UNAVAILABLE
    mode = str(daily_runtime.get("daily_target_mode") or "").lower()
    ready = bool(daily_runtime.get("daily_freshness_ready"))
    if mode == TARGET_CURRENT_PENDING:
        return DAILY_EOD_PENDING
    if mode == TARGET_PREVIOUS_COMPLETED:
        return DAILY_PREVIOUS_COMPLETED
    if mode == TARGET_CURRENT_READY:
        if ready:
            return DAILY_READY
        has_evidence = any(
            [
                int(daily_runtime.get("daily_checked_count") or 0) > 0,
                int(daily_runtime.get("daily_stale_count") or 0) > 0,
                bool(daily_runtime.get("daily_blocking_reason")),
                bool(daily_runtime.get("daily_stale_symbols")),
                bool(daily_runtime.get("daily_failed_symbols")),
            ]
        )
        return DAILY_FRESHNESS_BLOCKED if has_evidence else DAILY_RECONCILING
    if not ready and daily_runtime.get("daily_blocking_reason"):
        return DAILY_FRESHNESS_BLOCKED
    return DAILY_READY if ready else DAILY_UNAVAILABLE


def daily_data_state_from_freshness(freshness: dict[str, Any], *, book_available: bool = True) -> str:
    return daily_data_state_from_runtime(daily_freshness_fields_from_report(freshness), book_available=book_available)


def artifact_stage_from_artifact(artifact: Any) -> str:
    if artifact is None:
        return ARTIFACT_STAGE_NONE
    provider_meta = dict(getattr(artifact, "provider_meta", {}) or {})
    runtime_stage = str(provider_meta.get("runtime_stage") or "").strip().lower()
    reason = str(provider_meta.get("reason") or "").strip().lower()
    if runtime_stage == "daily" or reason == "daily_plan":
        return ARTIFACT_STAGE_DAILY_PLAN
    if runtime_stage == "minute" or reason == "intraday_pulse" or getattr(artifact, "slot_at", None):
        return ARTIFACT_STAGE_INTRADAY_PULSE
    return ARTIFACT_STAGE_UNKNOWN


def daily_plan_publish_meta(book: Any, *, market_phase: str) -> dict[str, Any]:
    daybook = getattr(book, "daybook", None)
    source_meta = getattr(daybook, "source_meta", {}) or {}
    freshness = dict(source_meta.get("daily_freshness") or {})
    return {
        "daybook_generated_at": getattr(daybook, "generated_at", None),
        "daily_target_day": freshness.get("target_day"),
        "daily_target_mode": freshness.get("target_mode"),
        "daily_last_reconcile_at": daily_last_reconcile_at(freshness),
        "market_phase": market_phase,
    }


def artifact_lag_status(
    *,
    book: Any,
    current_artifact: Any,
    artifact_stage: str,
    market_phase: str,
    daily_runtime: dict[str, Any],
) -> tuple[bool, str | None, list[str]]:
    if book is None:
        return False, None, []
    if not bool(daily_runtime.get("daily_freshness_ready")):
        return False, None, []
    if str(daily_runtime.get("daily_target_mode") or "").lower() != TARGET_CURRENT_READY:
        return False, None, []

    artifact_id = getattr(book, "artifact_id", None)
    if not artifact_id:
        return True, "daily_ready_current_artifact_missing", ["artifact_id"]
    if current_artifact is None:
        return True, "daily_ready_current_artifact_unavailable", ["artifact"]

    provider_meta = dict(getattr(current_artifact, "provider_meta", {}) or {})
    expected_meta = daily_plan_publish_meta(book, market_phase=market_phase)
    expected_meta.update(
        {
            "daily_target_day": daily_runtime.get("daily_target_day"),
            "daily_target_mode": daily_runtime.get("daily_target_mode"),
            "daily_last_reconcile_at": daily_runtime.get("daily_last_reconcile_at"),
        }
    )
    lag_fields: list[str] = []
    if artifact_stage != ARTIFACT_STAGE_DAILY_PLAN:
        lag_fields.append("runtime_stage")
    if provider_meta.get("reason") != "daily_plan":
        lag_fields.append("reason")
    for key in _DAILY_PLAN_META_KEYS:
        if key not in provider_meta or provider_meta.get(key) != expected_meta.get(key):
            lag_fields.append(key)
    if not lag_fields:
        return False, None, []
    return True, f"daily_ready_current_artifact_meta_mismatch:{','.join(lag_fields)}", lag_fields


def artifact_freshness_state(
    *,
    book: Any,
    current_artifact: Any,
    artifact_lagging: bool,
    daily_data_state: str,
    market_state: Any,
    intraday_runtime_enabled: bool,
) -> str:
    if book is None or current_artifact is None:
        return ARTIFACT_FRESHNESS_UNAVAILABLE
    if daily_data_state == DAILY_FRESHNESS_BLOCKED:
        return ARTIFACT_FRESHNESS_BLOCKED
    if artifact_lagging:
        return ARTIFACT_FRESHNESS_LAGGING
    target_slot_at = getattr(market_state, "target_pulse_slot_at", None)
    if intraday_runtime_enabled and target_slot_at and getattr(market_state, "market_phase", None) in _INTRADAY_SLOT_PHASES:
        book_slot = getattr(book, "pulse_slot_at", None) or getattr(book, "last_closed_5m", None)
        if not book_slot or str(book_slot) < str(target_slot_at):
            return ARTIFACT_FRESHNESS_LAGGING
    return ARTIFACT_FRESHNESS_CURRENT


def book_freshness_state(
    *,
    book: Any,
    market_phase: str,
    target_slot_at: str | None,
    intraday_runtime_enabled: bool,
    artifact_freshness: str,
    daily_data_state: str,
) -> str:
    if book is None:
        return DAILY_UNAVAILABLE
    if artifact_freshness == ARTIFACT_FRESHNESS_LAGGING:
        return "lagging"
    if daily_data_state in {DAILY_EOD_PENDING, DAILY_RECONCILING, DAILY_FRESHNESS_BLOCKED}:
        return daily_data_state
    if market_phase == PHASE_POSTCLOSE_PENDING and daily_data_state == DAILY_READY:
        return "postclose_ready"
    if not intraday_runtime_enabled:
        return "daily_only"
    slot_status = str(getattr(book, "slot_status", "") or "").upper()
    if slot_status and slot_status != "OK":
        return "degraded"
    if market_phase == PHASE_POSTCLOSE_PENDING:
        return "postclose_ready"
    if market_phase == PHASE_NON_TRADING:
        return "non_trading"
    if target_slot_at:
        book_slot = getattr(book, "pulse_slot_at", None) or getattr(book, "last_closed_5m", None)
        if book_slot and str(book_slot) >= str(target_slot_at):
            return "intraday_ready"
        return "intraday_lagging"
    return "waiting_first_bar"


def tradeability_state_from_book(book: Any) -> str:
    if book is None:
        return TRADEABILITY_BLOCKED
    gate = getattr(book, "gate", None)
    gate_state = str(getattr(gate, "state", "") or "").upper()
    if gate_state in {"BLOCKED", "KILLED"}:
        return TRADEABILITY_BLOCKED
    return TRADEABILITY_TRADEABLE if bool(getattr(book, "publish_allowed", False)) else TRADEABILITY_NO_TRADE


def build_runtime_state_snapshot(
    *,
    book: Any,
    market_state: Any,
    daily_target: dict[str, Any],
    latest_freshness_report: dict[str, Any] | None,
    current_artifact: Any,
    intraday_runtime_enabled: bool,
    repair_snapshot: Any = None,
) -> RuntimeStateSnapshot:
    daily_runtime = build_daily_runtime_fields(
        book=book,
        market_state=market_state,
        daily_target=daily_target,
        latest_freshness_report=latest_freshness_report,
        repair_snapshot=repair_snapshot,
    )
    daily_data_state = daily_data_state_from_runtime(daily_runtime, book_available=book is not None)
    artifact_stage = artifact_stage_from_artifact(current_artifact)
    artifact_lagging, artifact_lag_reason, artifact_lag_fields = artifact_lag_status(
        book=book,
        current_artifact=current_artifact,
        artifact_stage=artifact_stage,
        market_phase=getattr(market_state, "market_phase", ""),
        daily_runtime=daily_runtime,
    )
    artifact_freshness = artifact_freshness_state(
        book=book,
        current_artifact=current_artifact,
        artifact_lagging=artifact_lagging,
        daily_data_state=daily_data_state,
        market_state=market_state,
        intraday_runtime_enabled=intraday_runtime_enabled,
    )
    book_freshness = book_freshness_state(
        book=book,
        market_phase=getattr(market_state, "market_phase", ""),
        target_slot_at=getattr(market_state, "target_pulse_slot_at", None),
        intraday_runtime_enabled=intraday_runtime_enabled,
        artifact_freshness=artifact_freshness,
        daily_data_state=daily_data_state,
    )
    return RuntimeStateSnapshot(
        market_phase=str(getattr(market_state, "market_phase", "UNKNOWN")),
        clock_data_status=getattr(market_state, "data_status", None),
        daily_data_state=daily_data_state,
        daily_runtime={**daily_runtime, "daily_status": daily_data_state, "daily_data_state": daily_data_state},
        artifact_stage=artifact_stage,
        artifact_freshness=artifact_freshness,
        artifact_lag_reason=artifact_lag_reason,
        artifact_lag_fields=artifact_lag_fields,
        book_freshness=book_freshness,
        tradeability_state=tradeability_state_from_book(book),
        auto_update_expected=getattr(market_state, "market_phase", None) in _AUTO_UPDATE_PHASES,
    )
