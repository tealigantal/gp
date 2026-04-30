from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from ..book.engine import load_current_book
from ..book.repo import load_run, load_slot_artifact
from ..contracts.api import (
    BookResponse,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    OpsRunResponse,
    RunResponse,
    RuntimeStatus,
    RuntimeToolInfo,
    SessionResponse,
)
from ..core.config import load_config
from ..evidence.market_service import current_trading_day
from ..gateway.events import list_side_results
from ..gateway.sessions import get_session_diagnostics, get_session_payload, sanitize_chat_payload
from ..llm.client import LLMClient
from ..memory._sqlite import gateway_stats
from ..memory.session_store import list_sessions
from ..memory.transcript_store import load_recent
from ..runtime.lanes import book_lane, session_lane
from ..runtime.market_clock import (
    PHASE_CLOSING_AUCTION,
    PHASE_INTRADAY_AM,
    PHASE_INTRADAY_PM,
    PHASE_LUNCH_BREAK,
    PHASE_NON_TRADING,
    PHASE_OPEN_NO_FIRST_BAR,
    PHASE_POSTCLOSE_PENDING,
    PHASE_PREOPEN,
    compute_market_state,
)
from ..runtime.repair import load_repair_status_snapshot
from ..evidence.daily_freshness import resolve_daily_target
from ..runtime.turn_loop import run_turn_sync
from ..runtime.utils import now_iso
from ..worker import reconcile_runtime_state

router = APIRouter()


def _runtime_services() -> list[RuntimeToolInfo]:
    return [
        RuntimeToolInfo(
            service="gp",
            mode="always_on",
            command="uvicorn gp_assistant.gateway.app:app --host 0.0.0.0 --port 8000 --workers 2",
            description="主 API 服务，负责聊天、会话、book 和运行时状态读取。",
        ),
        RuntimeToolInfo(
            service="gp-worker",
            mode="always_on",
            command="python -m gp_assistant.cli pulse-loop",
            description="后台 worker，按市场时段自动修复日线、5 分钟线和 current artifact。",
        ),
        RuntimeToolInfo(
            service="gp-rebuild-daybook",
            mode="manual",
            profile="ops",
            command="python -m gp_assistant.cli rebuild-daybook",
            description="立即启动一次有边界的运行时修复。",
        ),
        RuntimeToolInfo(
            service="gp-replay-today",
            mode="manual",
            profile="ops",
            command="python -m gp_assistant.cli replay-today",
            description="重试当前市场时段对应的运行时修复计划。",
        ),
        RuntimeToolInfo(
            service="gp-postclose-archive",
            mode="manual",
            profile="ops",
            command="python -m gp_assistant.cli postclose-archive",
            description="执行显式 daily freshness audit，用于运维诊断。",
        ),
    ]


def _ops_executor(operation: str) -> tuple[str, Callable[[], dict[str, Any]]] | None:
    mapping: dict[str, tuple[str, Callable[[], dict[str, Any]]]] = {
        "gp-rebuild-daybook": (
            "已启动一次运行时修复。",
            lambda: reconcile_runtime_state(operation="rebuild_daybook"),
        ),
        "gp-replay-today": (
            "已重试当前运行时修复。",
            lambda: reconcile_runtime_state(operation="replay_today"),
        ),
        "gp-postclose-archive": (
            "已完成一次 daily freshness audit。",
            lambda: reconcile_runtime_state(operation="postclose_archive"),
        ),
    }
    return mapping.get(operation)


def _book_freshness(book, market_phase: str, target_slot_at: str | None, *, intraday_runtime_enabled: bool) -> str:
    if book is None:
        return "unavailable"
    if not intraday_runtime_enabled:
        return "daily_only"
    slot_status = str(getattr(book, "slot_status", "") or "").upper()
    if slot_status and slot_status != "OK":
        return "degraded"
    last_closed_5m = getattr(book, "last_closed_5m", None)
    if market_phase in {PHASE_PREOPEN, PHASE_OPEN_NO_FIRST_BAR} and not last_closed_5m:
        return "awaiting_first_slot"
    if target_slot_at and last_closed_5m:
        if str(last_closed_5m) >= str(target_slot_at):
            return "postclose_ready" if market_phase == PHASE_POSTCLOSE_PENDING else "current"
        return "lagging"
    if market_phase == PHASE_NON_TRADING:
        return "non_trading"
    if last_closed_5m:
        return "available"
    return "unavailable"


def _daily_freshness_fields(book) -> dict[str, Any]:
    source_meta = getattr(getattr(book, "daybook", None), "source_meta", {}) or {}
    freshness = dict(source_meta.get("daily_freshness") or {})
    return {
        "daily_freshness_ready": bool(freshness.get("ready", False)),
        "daily_target_day": freshness.get("target_day"),
        "daily_target_mode": freshness.get("target_mode"),
        "pending_eod_day": freshness.get("pending_eod_day"),
        "eod_probe": freshness.get("eod_probe"),
        "daily_checked_count": int(freshness.get("checked_count") or len(freshness.get("checked_symbols") or [])),
        "daily_stale_count": int(freshness.get("stale_count") or len(freshness.get("stale_symbols") or [])),
        "daily_last_reconcile_at": freshness.get("last_reconcile_at") or freshness.get("generated_at") or freshness.get("reconciled_at"),
        "daily_blocking_reason": freshness.get("blocking_reason"),
        "daily_failed_symbols": list(freshness.get("failed_symbols") or []),
    }


def _load_current_book_best_effort():
    try:
        with book_lane():
            return load_current_book(), None
    except TimeoutError as ex:
        return None, str(ex)


def _runtime_status(book, *, lock_error: str | None = None) -> RuntimeStatus:
    cfg = load_config()
    intraday_runtime_enabled = bool(getattr(cfg, "intraday_runtime_enabled", False))
    ms = compute_market_state()
    snapshot = load_repair_status_snapshot()
    auto_update_expected = ms.market_phase in {
        PHASE_PREOPEN,
        PHASE_OPEN_NO_FIRST_BAR,
        PHASE_INTRADAY_AM,
        PHASE_LUNCH_BREAK,
        PHASE_INTRADAY_PM,
        PHASE_CLOSING_AUCTION,
        PHASE_POSTCLOSE_PENDING,
    }
    daily_freshness = _daily_freshness_fields(book) if book else {}
    daily_target = resolve_daily_target(ms.target_daybook_effective_day, allow_probe=False)
    daily_target_day = daily_target.get("target_day") or daily_freshness.get("daily_target_day")
    daily_target_mode = daily_target.get("target_mode") or daily_freshness.get("daily_target_mode")
    pending_eod_day = (
        daily_target.get("pending_eod_day")
        if "pending_eod_day" in daily_target
        else daily_freshness.get("pending_eod_day")
    )
    eod_probe = (
        daily_target.get("eod_probe")
        if "eod_probe" in daily_target
        else daily_freshness.get("eod_probe")
    )
    source_target_day = daily_freshness.get("daily_target_day")
    if source_target_day and daily_target_day and str(source_target_day) != str(daily_target_day):
        daily_freshness = {
            **daily_freshness,
            "daily_freshness_ready": False,
            "daily_checked_count": 0,
            "daily_stale_count": 0,
            "daily_last_reconcile_at": None,
            "daily_blocking_reason": None,
            "daily_failed_symbols": [],
        }
    daily_runtime = {
        **daily_freshness,
        "daily_target_day": str(daily_target_day) if daily_target_day else (snapshot.daily_target_day if snapshot else None),
        "daily_target_mode": str(daily_target_mode) if daily_target_mode else None,
        "pending_eod_day": str(pending_eod_day) if pending_eod_day else None,
        "eod_probe": eod_probe if isinstance(eod_probe, dict) else None,
    }
    return RuntimeStatus(
        market_phase=str(snapshot.market_phase if snapshot else ms.market_phase),
        data_provider=str(getattr(cfg.provider, "data_provider", "unknown") or "unknown"),
        auto_update_service="gp-worker",
        auto_update_expected=auto_update_expected,
        intraday_runtime_enabled=intraday_runtime_enabled,
        worker_poll_interval_sec=max(5, int(getattr(cfg, "intraday_poll_interval_sec", 15) or 15)),
        book_freshness=_book_freshness(
            book,
            ms.market_phase,
            ms.target_pulse_slot_at,
            intraday_runtime_enabled=intraday_runtime_enabled,
        ),
        book_updated_at=(getattr(book, "updated_at", None) if book else None),
        artifact_id=(getattr(book, "artifact_id", None) if book else None),
        daybook_effective_day=(getattr(book, "daybook_effective_day", None) if book else None),
        pulse_trade_day=(getattr(book, "pulse_trade_day", None) if book else None),
        pulse_slot_at=(getattr(book, "pulse_slot_at", None) if book else None),
        last_closed_5m=(getattr(book, "last_closed_5m", None) if book else None),
        slot_status=(getattr(book, "slot_status", None) if book else None),
        publish_allowed=bool(getattr(book, "publish_allowed", False) if book else False),
        repair_status=str(snapshot.repair_status if snapshot else "idle"),
        repair_stage=str(snapshot.repair_stage if snapshot else "idle"),
        pulse_target_trade_day=(snapshot.pulse_target_trade_day if snapshot else ms.target_pulse_trade_day),
        pulse_target_slot_at=(snapshot.pulse_target_slot_at if snapshot else ms.target_pulse_slot_at),
        last_repair_started_at=(snapshot.last_repair_started_at if snapshot else None),
        last_repair_finished_at=(snapshot.last_repair_finished_at if snapshot else None),
        blocking_reason=(
            snapshot.blocking_reason
            if snapshot and snapshot.blocking_reason
            else (
                lock_error
                if lock_error
                else (
                    "当前配置已关闭盘中 5 分钟接入，仅保留日级计划与观察状态。"
                    if not intraday_runtime_enabled
                    else None
                )
            )
        ),
        artifact_status=str(snapshot.artifact_status if snapshot else (getattr(book, "slot_status", None) or "unavailable")),
        services=_runtime_services(),
        **daily_runtime,
    )


@router.post("/chat", response_model=ChatResponse)
@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or "default"
    with session_lane(session_id):
        out = run_turn_sync(session_id=session_id, user_message=req.message)
    return ChatResponse(**sanitize_chat_payload(out))


@router.get("/health", response_model=HealthResponse)
@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    book, lock_error = _load_current_book_best_effort()
    ok, _ = LLMClient().available()
    return HealthResponse(
        status="ok",
        trading_day=current_trading_day(),
        book_version=(book.book_version if book else None),
        llm_ready=ok,
        storage=gateway_stats(),
        runtime=_runtime_status(book, lock_error=lock_error),
    )


@router.get("/api/ops/repair/status")
def repair_status() -> dict[str, Any]:
    book, lock_error = _load_current_book_best_effort()
    return {"runtime": _runtime_status(book, lock_error=lock_error).model_dump()}


@router.post("/api/ops/repair/{operation}", response_model=OpsRunResponse)
def run_repair_ops(operation: str) -> OpsRunResponse:
    executor = _ops_executor(operation)
    if executor is None:
        raise HTTPException(status_code=404, detail=f"Unknown repair operation: {operation}")
    default_message, fn = executor
    result = fn()
    book, lock_error = _load_current_book_best_effort()
    status = "blocked" if bool(result.get("blocked")) else "ok"
    message = result.get("message") or default_message
    return OpsRunResponse(
        operation=operation,
        status=status,
        message=message,
        executed_at=now_iso(),
        result=result,
        runtime=_runtime_status(book, lock_error=lock_error),
    )


@router.get("/api/book/current", response_model=BookResponse)
def current_book() -> BookResponse:
    book, _lock_error = _load_current_book_best_effort()
    return BookResponse(book=book.model_dump() if book else {})


@router.get("/api/book/slot/{artifact_id}", response_model=BookResponse)
def slot_book(artifact_id: str) -> BookResponse:
    artifact = load_slot_artifact(artifact_id)
    return BookResponse(book=(artifact.model_dump() if artifact else {}))


@router.get("/api/run/{run_id}", response_model=RunResponse)
def get_run(run_id: str) -> RunResponse:
    run = load_run(run_id)
    return RunResponse(run=run.model_dump() if run else {})


@router.get("/api/session/{session_id}", response_model=SessionResponse)
def get_session(session_id: str) -> SessionResponse:
    return SessionResponse(**get_session_payload(session_id))


@router.get("/api/session/{session_id}/diagnostics")
def get_session_diagnostics_view(session_id: str) -> dict[str, Any]:
    return get_session_diagnostics(session_id)


@router.get("/api/side-results")
def side_results() -> list[dict]:
    return list_side_results()


@router.get("/api/sessions")
def list_session_overviews(limit: int = 20) -> list[dict]:
    out: list[dict] = []
    for s in list_sessions(limit=limit):
        turns = load_recent(s.session_id, limit=4)
        title = None
        preview = None
        for t in reversed(turns):
            if t.role == "assistant" and not preview:
                preview = t.content[:120]
            if t.role == "user" and not title:
                title = t.content[:40]
        out.append(
            {
                "session_id": s.session_id,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "title": title or "新会话",
                "preview": preview or "",
                "active_run_id": s.active_run_id,
            }
        )
    return out
