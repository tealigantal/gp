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
from ..evidence.daily_freshness import audit_daily_freshness, book_symbols, load_latest_daily_freshness_report
from ..evidence.market_service import current_trading_day
from ..gateway.events import list_side_results
from ..gateway.sessions import get_session_payload, sanitize_chat_payload
from ..runtime.lanes import book_lane, session_lane
from ..llm.client import LLMClient
from ..memory._sqlite import gateway_stats
from ..memory.session_store import list_sessions
from ..memory.transcript_store import load_recent
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
            description="对外 API 服务，负责聊天、book、session 和 run 查询。",
        ),
        RuntimeToolInfo(
            service="gp-worker",
            mode="always_on",
            command="python -m gp_assistant.cli pulse-loop",
            description="常驻 5 分钟 worker，按当前市场时段自动做运行时 reconcile。",
        ),
        RuntimeToolInfo(
            service="gp-rebuild-daybook",
            mode="manual",
            profile="ops",
            command="python -m gp_assistant.cli rebuild-daybook",
            description="先校验日线 freshness，再重建当日 daybook 和盘前初始化产物。",
        ),
        RuntimeToolInfo(
            service="gp-replay-today",
            mode="manual",
            profile="ops",
            command="python -m gp_assistant.cli replay-today",
            description="只回放今天已收盘的 5 分钟 slot，不修日线。",
        ),
        RuntimeToolInfo(
            service="gp-postclose-archive",
            mode="manual",
            profile="ops",
            command="python -m gp_assistant.cli postclose-archive",
            description="只处理收盘后状态补齐和归档，不修日线。",
        ),
    ]


def _ops_executor(service: str) -> tuple[str, Callable[[], dict[str, Any]]] | None:
    mapping: dict[str, tuple[str, Callable[[], dict[str, Any]]]] = {
        "gp-rebuild-daybook": (
            "已重建当日 daybook 和盘前初始化产物。",
            lambda: reconcile_runtime_state(operation="rebuild_daybook"),
        ),
        "gp-replay-today": (
            "已按当前时点回放今天已收盘的 5 分钟 slot。",
            lambda: reconcile_runtime_state(operation="replay_today"),
        ),
        "gp-postclose-archive": (
            "已补齐收盘后状态并执行归档。",
            lambda: reconcile_runtime_state(operation="postclose_archive"),
        ),
    }
    return mapping.get(service)


def _book_freshness(book, market_phase: str, target_slot_at: str | None) -> str:
    if book is None:
        return "unavailable"
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


def _runtime_status(book) -> RuntimeStatus:
    cfg = load_config()
    ms = compute_market_state()
    auto_update_expected = ms.market_phase in {
        PHASE_PREOPEN,
        PHASE_OPEN_NO_FIRST_BAR,
        PHASE_INTRADAY_AM,
        PHASE_LUNCH_BREAK,
        PHASE_INTRADAY_PM,
        PHASE_CLOSING_AUCTION,
        PHASE_POSTCLOSE_PENDING,
    }
    audit = audit_daily_freshness(symbols=book_symbols(book) if book else [], as_of=ms.target_daybook_effective_day, limit=10)
    latest_report = load_latest_daily_freshness_report() or {}
    blocking_reason = None
    if audit.get("focus_stale_symbols"):
        blocking_reason = f"今天日线还没补齐到 {audit['target_day']}，当前不发布正式推荐。"
    return RuntimeStatus(
        market_phase=ms.market_phase,
        data_provider=str(getattr(cfg.provider, "data_provider", "unknown") or "unknown"),
        auto_update_service="gp-worker",
        auto_update_expected=auto_update_expected,
        worker_poll_interval_sec=max(5, int(getattr(cfg, "intraday_poll_interval_sec", 15) or 15)),
        book_freshness=_book_freshness(book, ms.market_phase, ms.target_pulse_slot_at),
        book_updated_at=(getattr(book, "updated_at", None) if book else None),
        artifact_id=(getattr(book, "artifact_id", None) if book else None),
        daybook_effective_day=(getattr(book, "daybook_effective_day", None) if book else None),
        pulse_trade_day=(getattr(book, "pulse_trade_day", None) if book else None),
        pulse_slot_at=(getattr(book, "pulse_slot_at", None) if book else None),
        last_closed_5m=(getattr(book, "last_closed_5m", None) if book else None),
        slot_status=(getattr(book, "slot_status", None) if book else None),
        publish_allowed=bool(getattr(book, "publish_allowed", False) if book else False),
        daily_freshness_ready=not bool(audit.get("focus_stale_symbols")),
        daily_target_day=audit.get("target_day"),
        daily_checked_count=len(audit.get("focus_symbols") or []),
        daily_stale_count=len(audit.get("focus_stale_symbols") or []),
        daily_last_reconcile_at=latest_report.get("last_reconcile_at"),
        daily_blocking_reason=blocking_reason or latest_report.get("blocking_reason"),
        daily_failed_symbols=list((latest_report.get("failed_symbols") or [])[:10]),
        services=_runtime_services(),
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
    book = load_current_book()
    ok, _ = LLMClient().available()
    return HealthResponse(
        status="ok",
        trading_day=current_trading_day(),
        book_version=(book.book_version if book else None),
        llm_ready=ok,
        storage=gateway_stats(),
        runtime=_runtime_status(book),
    )


@router.get("/api/health/daily-freshness")
def daily_freshness_health() -> dict[str, Any]:
    book = load_current_book()
    return audit_daily_freshness(symbols=book_symbols(book) if book else [], as_of=current_trading_day(), limit=25)


@router.post("/api/ops/{service}/run", response_model=OpsRunResponse)
def run_ops(service: str) -> OpsRunResponse:
    executor = _ops_executor(service)
    if executor is None:
        raise HTTPException(status_code=404, detail=f"Unknown ops service: {service}")
    default_message, fn = executor
    with book_lane():
        result = fn()
        book = load_current_book()
    status = "blocked" if bool(result.get("blocked")) else "ok"
    message = (
        result.get("message")
        or result.get("daily_freshness", {}).get("blocking_reason")
        or default_message
    )
    return OpsRunResponse(
        operation=service,
        status=status,
        message=message,
        executed_at=now_iso(),
        result=result,
        runtime=_runtime_status(book),
    )


@router.get("/api/book/current", response_model=BookResponse)
def current_book() -> BookResponse:
    with book_lane():
        book = load_current_book()
    return BookResponse(book=book.model_dump())


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
                "title": title or "对话",
                "preview": preview or "",
                "active_run_id": s.active_run_id,
            }
        )
    return out
