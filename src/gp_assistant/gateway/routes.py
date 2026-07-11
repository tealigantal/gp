from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ..book.engine import load_current_book
from ..book.repo import load_run, load_slot_artifact
from ..contracts.api import (
    BookResponse,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    OpsRunResponse,
    RunResponse,
    SerenityRuntimeStatus,
    RuntimeStatus,
    RuntimeToolInfo,
    SessionResponse,
)
from ..core.config import load_config
from ..core.errors import APIError, IntentLLMUnavailable, IntentParseFailed, LLMPayloadBudgetExceeded
from ..evidence.market_service import current_trading_day
from ..gateway.events import list_side_results
from ..gateway.sessions import get_session_diagnostics, get_session_payload, sanitize_chat_payload
from ..kernel import facade as kernel_facade
from ..llm.client import LLMClient
from ..memory._sqlite import gateway_stats
from ..memory.session_store import list_sessions
from ..memory.transcript_store import load_recent
from ..runtime.lanes import session_lane
from ..runtime.market_clock import compute_market_state
from ..runtime.repair import load_repair_status_snapshot
from ..evidence.daily_freshness import load_latest_daily_freshness_report, resolve_daily_target
from ..runtime.slot_state import build_runtime_state_snapshot
from ..runtime.turn_loop import run_turn_sync
from ..runtime.utils import now_iso
from ..worker import reconcile_runtime_state
from ..serenity.store import status_snapshot as serenity_status_snapshot
from ..runtime.producer import producer_is_compatible, producer_metadata

router = APIRouter()


def _artifact_not_found(error: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "ok": False,
            "artifact_version": "v2",
            "error": error,
        },
    )


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
            command="python -m gp_assistant.cli runtime-loop",
            description="后台 worker，按统一运行链刷新日线、盘中分钟线和 current artifact。",
        ),
        RuntimeToolInfo(
            service="gp-serenity-worker",
            mode="experimental",
            profile="experiments",
            command="python -m gp_assistant.cli serenity-loop",
            description="免费官方公告实验采集器；独立于核心选股和聊天请求链。",
        ),
        RuntimeToolInfo(
            service="gp-rebuild-daybook",
            mode="manual",
            profile="ops",
            command="python -m gp_assistant.cli ops-run rebuild-daybook",
            description="立即启动一次有边界的运行时修复。",
        ),
        RuntimeToolInfo(
            service="gp-postclose-archive",
            mode="manual",
            profile="ops",
            command="python -m gp_assistant.cli ops-run postclose-archive",
            description="执行显式 daily freshness audit，用于运维诊断。",
        ),
    ]


def _ops_executor(operation: str) -> tuple[str, Callable[[], dict[str, Any]]] | None:
    mapping: dict[str, tuple[str, Callable[[], dict[str, Any]]]] = {
        "gp-rebuild-daybook": (
            "已启动一次运行时修复。",
            lambda: reconcile_runtime_state(operation="rebuild_daybook"),
        ),
        "gp-postclose-archive": (
            "已完成一次 daily freshness audit。",
            lambda: reconcile_runtime_state(operation="postclose_archive"),
        ),
    }
    return mapping.get(operation)


def _load_current_book_best_effort():
    try:
        return load_current_book(), None
    except Exception as ex:  # noqa: BLE001
        return None, str(ex)


def _runtime_status(book, *, lock_error: str | None = None) -> RuntimeStatus:
    cfg = load_config()
    intraday_runtime_enabled = bool(getattr(cfg, "intraday_runtime_enabled", False))
    ms = compute_market_state()
    snapshot = load_repair_status_snapshot()
    daily_target = resolve_daily_target(ms.target_daybook_effective_day, allow_probe=False)
    latest_report = load_latest_daily_freshness_report() or {}
    current_artifact = (
        load_slot_artifact(str(getattr(book, "artifact_id", "")), trade_day=getattr(book, "trading_day", None))
        if book and getattr(book, "artifact_id", None)
        else None
    )
    runtime_state = build_runtime_state_snapshot(
        book=book,
        market_state=ms,
        daily_target=daily_target,
        latest_freshness_report=latest_report,
        current_artifact=current_artifact,
        intraday_runtime_enabled=intraday_runtime_enabled,
        repair_snapshot=snapshot,
    )
    daily_runtime = dict(runtime_state.daily_runtime)
    try:
        serenity_runtime = SerenityRuntimeStatus.model_validate(serenity_status_snapshot())
    except Exception as ex:  # noqa: BLE001
        serenity_runtime = SerenityRuntimeStatus(mode=str(getattr(getattr(cfg, "serenity", None), "mode", "off")), state="warming", reason=f"{type(ex).__name__}: {ex}")
    return RuntimeStatus(
        market_phase=runtime_state.market_phase,
        calendar_source=ms.calendar_source,
        calendar_status=ms.calendar_status,
        calendar_range={"start": ms.calendar_range_start, "end": ms.calendar_range_end},
        calendar_error=ms.calendar_error,
        next_trading_day=ms.next_trading_day,
        data_provider=str(getattr(cfg.provider, "data_provider", "unknown") or "unknown"),
        auto_update_service="gp-worker",
        auto_update_expected=runtime_state.auto_update_expected,
        intraday_runtime_enabled=intraday_runtime_enabled,
        worker_poll_interval_sec=max(5, int(getattr(cfg, "intraday_poll_interval_sec", 15) or 15)),
        book_freshness=runtime_state.book_freshness,
        book_updated_at=(getattr(book, "updated_at", None) if book else None),
        artifact_id=(getattr(book, "artifact_id", None) if book else None),
        daybook_effective_day=(getattr(book, "daybook_effective_day", None) if book else None),
        pulse_trade_day=(getattr(book, "pulse_trade_day", None) if book else None),
        pulse_slot_at=(getattr(book, "pulse_slot_at", None) if book else None),
        last_closed_5m=(getattr(book, "last_closed_5m", None) if book else None),
        slot_status=(getattr(book, "slot_status", None) if book else None),
        data_quality=(
            book.data_quality.model_dump()
            if book and getattr(book, "data_quality", None) is not None and hasattr(book.data_quality, "model_dump")
            else {}
        ),
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
                    "盘中运行链已关闭，仅使用日线计划模块。"
                    if not intraday_runtime_enabled
                    else None
                )
            )
        ),
        clock_data_status=runtime_state.clock_data_status,
        artifact_stage=runtime_state.artifact_stage,
        artifact_freshness=runtime_state.artifact_freshness,
        artifact_status=runtime_state.artifact_status,
        artifact_lag_reason=runtime_state.artifact_lag_reason,
        artifact_lag_fields=runtime_state.artifact_lag_fields,
        tradeability_state=runtime_state.tradeability_state,
        services=_runtime_services(),
        serenity=serenity_runtime,
        producer=producer_metadata(),
        current_artifact_compatible=bool(book and producer_is_compatible(getattr(book, "producer", None))),
        **daily_runtime,
    )


@router.post("/chat", response_model=ChatResponse)
@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or "default"
    try:
        with session_lane(session_id):
            out = run_turn_sync(session_id=session_id, user_message=req.message)
    except IntentLLMUnavailable as ex:
        raise APIError(
            status_code=503,
            message="LLM 意图解析服务不可用",
            detail={"reason": ex.reason},
        ) from ex
    except IntentParseFailed as ex:
        raise APIError(
            status_code=502,
            message="LLM 意图解析返回无效结果",
            detail=ex.detail(),
        ) from ex
    except LLMPayloadBudgetExceeded as ex:
        raise APIError(
            status_code=500,
            message="LLM 上下文超过预算",
            detail=ex.detail(),
        ) from ex
    return ChatResponse(**sanitize_chat_payload(out))


@router.get("/api/recommend_v2")
def recommend_v2(run_id: str | None = None, as_of: str | None = None):
    try:
        return kernel_facade.get_artifact_v2(run_id=run_id, as_of=as_of)
    except FileNotFoundError:
        return _artifact_not_found("recommend_v2_unavailable")


@router.post("/api/compare")
def compare_symbols(body: dict[str, Any]):
    run_id = body.get("run_id") or body.get("as_of")
    raw_symbols = body.get("symbols") or []
    symbols = [str(symbol).strip() for symbol in raw_symbols if str(symbol).strip()] if isinstance(raw_symbols, list) else []
    try:
        return kernel_facade.compare_symbols(str(run_id) if run_id else None, symbols)
    except FileNotFoundError:
        return _artifact_not_found("recommend_v2_unavailable")


@router.get("/api/pick")
def pick_detail(run_id: str | None = None, symbol: str | None = None):
    if not symbol:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "artifact_version": "v2", "error": "symbol_required"},
        )
    try:
        return kernel_facade.get_pick_detail(run_id, symbol)
    except FileNotFoundError:
        return _artifact_not_found("recommend_v2_unavailable")


@router.get("/api/validation/summary")
def validation_summary():
    return kernel_facade.get_validation_summary()


@router.get("/api/workbench")
def workbench(run_id: str | None = None, as_of: str | None = None):
    try:
        return kernel_facade.get_workbench_snapshot(run_id=run_id, as_of=as_of)
    except FileNotFoundError:
        return _artifact_not_found("recommend_v2_unavailable")


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
