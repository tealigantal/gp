from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ..agent_store import AgentStore, AgentStoreError, SnapshotIntegrityError, StorageBusyError
from ..chat_agent import _current_serenity_check, run_chat_turn
from ..contracts.api import (
    BookResponse,
    ChatHistoryResponse,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    HealthStorageStats,
    LunchResponse,
    RuntimeStatus,
    RuntimeToolInfo,
    SessionResponse,
)
from ..core.errors import APIError, IntentLLMUnavailable, IntentParseFailed, LLMPayloadBudgetExceeded
from ..llm.client import llm_status
from ..runtime.market_time import compare_snapshot_market_time
from ..runtime.native_snapshot import (
    native_snapshot_integrity_errors,
    pending_native_snapshot_integrity_errors,
)
from ..evidence.daily_freshness import resolve_daily_target
from ..search.history_store import history_db_path
from ..serenity.store import status_snapshot as serenity_status_snapshot
from ..runtime.utils import now_iso


router = APIRouter()


def _history_health() -> dict[str, Any]:
    path = history_db_path()
    return {"path": str(path), "exists": path.exists(), "bytes": path.stat().st_size if path.exists() else 0}


def _workspace_runtime(store: AgentStore, snapshot: Any | None) -> RuntimeStatus:
    """Expose the current immutable snapshot through the Workspace read model."""
    book = store.book_for_snapshot(snapshot) if snapshot else None
    market_phase = str(
        getattr(book, "market_phase", None)
        or getattr(snapshot, "market_phase", None)
        or "UNKNOWN"
    )
    target_mode = str(getattr(snapshot, "target_mode", None) or "unavailable")
    has_book = book is not None
    candidate_universe = dict(getattr(book, "candidate_universe", None) or {}) if book else {}
    universe_quality = dict(getattr(book, "universe_quality", None) or candidate_universe) if book else {}
    counts = dict(candidate_universe.get("counts") or {})
    universe_ready = bool(candidate_universe.get("complete"))
    return RuntimeStatus(
        market_phase=market_phase,
        data_provider=str(os.getenv("DATA_PROVIDER") or "akshare"),
        auto_update_service="gp-worker",
        auto_update_expected=True,
        intraday_runtime_enabled=False,
        book_freshness=("postclose_ready" if market_phase == "NON_TRADING" else "current") if has_book else "unavailable",
        book_updated_at=(getattr(book, "updated_at", None) if book else None),
        artifact_id=(getattr(book, "artifact_id", None) if book else None),
        daybook_effective_day=(getattr(book, "daybook_effective_day", None) if book else None),
        pulse_trade_day=(getattr(book, "pulse_trade_day", None) if book else None),
        pulse_slot_at=(getattr(book, "pulse_slot_at", None) if book else None),
        last_closed_5m=(getattr(book, "last_closed_5m", None) if book else None),
        slot_status=(getattr(book, "slot_status", None) if book else None),
        publish_allowed=bool(getattr(book, "publish_allowed", False)),
        daily_data_state=target_mode,
        daily_freshness_ready=bool(has_book and universe_ready),
        daily_target_day=(getattr(snapshot, "daybook_effective_day", None) if snapshot else None),
        daily_target_mode=target_mode,
        artifact_stage=("daily_plan" if has_book else "none"),
        artifact_freshness=("current" if has_book else "unavailable"),
        artifact_status=("ready" if has_book else "unavailable"),
        tradeability_state=("tradeable" if bool(getattr(snapshot, "tradeable", False)) else "no_trade"),
        daily_checked_count=int(counts.get("mainboard_input_count") or 0),
        daily_stale_count=max(
            0,
            int(counts.get("mainboard_input_count") or 0)
            - int(counts.get("daily_ready_count") or 0),
        ),
        daily_blocking_reason=candidate_universe.get("blocking_reason"),
        blocking_reason=candidate_universe.get("blocking_reason"),
        candidate_universe=candidate_universe,
        universe_quality=universe_quality,
        services=[
            RuntimeToolInfo(service="gp", mode="always_on", command="uvicorn gp_assistant.gateway.app:app", description="聊天与快照 API"),
            RuntimeToolInfo(service="gp-worker", mode="always_on", command="python -m gp_assistant.cli runtime-loop", description="日线计划刷新"),
            RuntimeToolInfo(service="gp-serenity-worker", mode="always_on", command="python -m gp_assistant.cli serenity-loop", description="Serenity 官方公告采集"),
        ],
    )


def _workspace_session_payload(store: AgentStore, session_id: str) -> dict[str, Any]:
    record = store.session_record(session_id)
    created_at = str((record or {}).get("created_at") or now_iso())
    updated_at = str((record or {}).get("updated_at") or created_at)
    snapshot_id = (record or {}).get("active_snapshot_id")
    snapshot = store.load_snapshot(str(snapshot_id)) if snapshot_id else None
    book = store.book_for_snapshot(snapshot) if snapshot else None
    turns: list[dict[str, Any]] = []
    for turn in store.session_turns(session_id):
        payload = dict(turn.get("payload") or {}) if turn.get("role") == "assistant" else {}
        payload.pop("llm_trace", None)
        turns.append(
            {
                "seq": turn["seq"],
                "turn_id": turn["turn_id"],
                "session_id": session_id,
                "role": turn["role"],
                "content": turn["content"],
                "created_at": turn["created_at"],
                "meta": payload,
            }
        )
    return {
        "session": {
            "session_id": session_id,
            "created_at": created_at,
            "updated_at": updated_at,
            "active_run_id": snapshot_id,
            "previous_run_id": None,
            "focus_subject": {},
            "compare_set": [],
            "user_preferences": {},
            "last_seen_book_version": getattr(book, "book_version", None),
            "last_turn_id": (record or {}).get("last_turn_id"),
            "last_claim_ids": [],
        },
        "recent_turns": turns,
        "recent_claims": [],
    }


def _workspace_diagnostics(store: AgentStore, session_id: str) -> dict[str, Any]:
    session_payload = _workspace_session_payload(store, session_id)
    assistant_messages: list[dict[str, Any]] = []
    for turn in reversed(session_payload["recent_turns"]):
        if turn["role"] != "assistant":
            continue
        meta = dict(turn.get("meta") or {})
        message = dict(meta.get("message") or {})
        symbols = list(meta.get("symbols") or [])
        assistant_messages.append(
            {
                "turn_id": turn["turn_id"],
                "seq": turn["seq"],
                "created_at": turn["created_at"],
                "message_kind": message.get("message_kind") or meta.get("decision"),
                "narrative_text": message.get("narrative_text") or meta.get("reply"),
                "symbol": message.get("symbol") or (symbols[0] if symbols else None),
                "run_action": (message.get("run") or {}).get("run_action") if isinstance(message.get("run"), dict) else meta.get("decision"),
                "followup_suggestions": list(message.get("followup_suggestions") or []),
            }
        )
        if len(assistant_messages) == 6:
            break
    return {
        "session_id": session_id,
        "focus": {
            "active_run_id": session_payload["session"].get("active_run_id"),
            "previous_run_id": None,
            "last_focus_symbol": None,
            "last_focus_rank": None,
            "compare_set": [],
        },
        "latest_assistant": assistant_messages[0] if assistant_messages else None,
        "assistant_messages": assistant_messages,
    }


@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        return ChatResponse(**run_chat_turn(
            session_id=req.session_id,
            client_turn_id=req.client_turn_id,
            user_message=req.message,
        ))
    except SnapshotIntegrityError as ex:
        raise APIError(status_code=503, message="推荐快照完整性校验失败", detail={"reason": str(ex)}) from ex
    except StorageBusyError as ex:
        raise APIError(status_code=503, message="存储繁忙，请稍后重试", detail={"reason": str(ex), "retry_after_ms": ex.retry_after_ms}) from ex
    except AgentStoreError as ex:
        raise APIError(status_code=409, message="聊天写入被拒绝", detail={"reason": str(ex)}) from ex
    except IntentLLMUnavailable as ex:
        raise APIError(status_code=503, message="LLM 意图解析服务不可用", detail={"reason": ex.reason}) from ex
    except IntentParseFailed as ex:
        raise APIError(status_code=502, message="LLM 意图解析失败", detail=ex.detail()) from ex
    except LLMPayloadBudgetExceeded as ex:
        raise APIError(status_code=502, message="LLM 上下文超过安全预算", detail=ex.detail()) from ex


@router.get("/api/chat/{session_id}", response_model=ChatHistoryResponse)
def chat_history(session_id: str) -> ChatHistoryResponse:
    turns = AgentStore().session_turns(session_id)
    if not turns:
        raise HTTPException(status_code=404, detail="session_not_found")
    return ChatHistoryResponse(session_id=session_id, turns=turns)


@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    store = AgentStore()
    try:
        health = store.health_snapshot()
    except StorageBusyError as ex:
        raise APIError(
            status_code=503,
            message="健康检查无法读取真实存储",
            detail={"reason": str(ex), "retry_after_ms": ex.retry_after_ms},
        ) from ex
    snapshot = health.pop("snapshot")
    llm = llm_status()
    serenity_telemetry = serenity_status_snapshot()
    readiness_reasons: list[str] = []
    snapshot_target_id = None
    snapshot_readiness_revision = None
    active_readiness_revision = None
    snapshot_semantic_revision = None
    active_semantic_revision = None
    snapshot_native_ready = False
    runtime_contract: dict[str, Any] = {}
    runtime_contract_ready = False
    market_time = None
    atomic_serenity: dict[str, Any] = {}
    serenity_reason: str | None = None
    candidate_universe: dict[str, Any] = {}
    snapshot_serenity_policy: dict[str, Any] = {}
    try:
        market_time = resolve_daily_target(allow_probe=False)
        runtime_contract = market_time.as_dict()
    except Exception as ex:  # noqa: BLE001
        readiness_reasons.append(f"当前市场时间契约不可用：{type(ex).__name__}")
    if snapshot is None:
        readiness_reasons.append("当前推荐快照不存在")
    else:
        try:
            book = store.book_for_snapshot(snapshot)
            source_meta = dict(book.daybook.source_meta or {})
            snapshot_serenity_policy = dict(source_meta.get("serenity_policy_snapshot") or {})
            candidate_universe = dict(
                getattr(book, "candidate_universe", None)
                or source_meta.get("candidate_universe")
                or {}
            )
            universe_ready = bool(candidate_universe.get("complete"))
            if not universe_ready:
                if not candidate_universe:
                    readiness_reasons.append(
                        "当前快照缺少全市场候选宇宙契约：legacy_coverage_unverified"
                    )
                else:
                    readiness_reasons.append(
                        "当前全市场候选宇宙不完整："
                        + str(candidate_universe.get("blocking_reason") or "candidate_universe_incomplete")
                    )
            snapshot_target_id = str(source_meta.get("serenity_target_id") or "") or None
            snapshot_readiness_revision = str(
                source_meta.get("serenity_readiness_revision") or ""
            ) or None
            snapshot_semantic_revision = str(
                source_meta.get("serenity_semantic_revision") or ""
            ) or None
            pending_snapshot = not bool(book.daybook.picks)
            integrity_errors = (
                pending_native_snapshot_integrity_errors(snapshot, book)
                if pending_snapshot
                else native_snapshot_integrity_errors(snapshot, book)
            )
            if integrity_errors:
                readiness_reasons.append(
                    f"当前推荐快照未通过 Serenity 原生完整性校验：{integrity_errors[0]}"
                )
            else:
                market_state = (
                    compare_snapshot_market_time(snapshot, market_time)
                    if market_time is not None
                    else {"matches": False, "mismatches": []}
                )
                if not bool(market_state.get("matches")):
                    readiness_reasons.append(
                        "当前推荐快照不符合市场时间契约："
                        + ",".join(market_state.get("mismatches") or [])
                    )
                else:
                    runtime_contract_ready = True
                serenity_reason, atomic_serenity = _current_serenity_check(book)
                active_readiness_revision = str(
                    atomic_serenity.get("readiness_revision") or ""
                ) or None
                active_semantic_revision = str(
                    atomic_serenity.get("semantic_revision") or ""
                ) or None
                serenity_weight = float(
                    dict(source_meta.get("serenity_policy_snapshot") or {}).get("applied_weight")
                    or 0.0
                )
                serenity_blocks = bool(serenity_reason and serenity_weight > 0.0)
                if serenity_blocks:
                    readiness_reasons.append(
                        f"当前推荐快照的 Serenity 绑定已失效：{serenity_reason}"
                    )
                gate_compatible = not (
                    snapshot.decision == "recommend"
                    and str(book.gate.state or "").upper() != "ALLOW"
                )
                if not gate_compatible:
                    readiness_reasons.append(
                        "当前推荐快照的市场门控不允许推荐动作"
                    )
                snapshot_native_ready = bool(
                    universe_ready
                    and runtime_contract_ready
                    and not serenity_blocks
                    and gate_compatible
                )
        except Exception as ex:  # noqa: BLE001
            readiness_reasons.append(f"当前推荐快照协议校验失败：{type(ex).__name__}")
    if llm.get("verification") != "ready":
        readiness_reasons.append(f"LLM 尚未通过真实调用验证：{llm.get('verification') or '未知状态'}")
    product_ready = bool(snapshot_native_ready and not readiness_reasons)
    serenity = {
        **serenity_telemetry,
        "available": bool(
            atomic_serenity.get("available") and serenity_reason is None
        ),
        "reason": serenity_reason,
        "atomic_readiness": atomic_serenity,
    }
    session_overviews = store.session_overviews(limit=1)
    return HealthResponse(
        status="ok" if product_ready else "degraded",
        product_ready=product_ready,
        readiness_reasons=readiness_reasons,
        agent_db=health,
        current_snapshot=(
            {"snapshot_id": snapshot.snapshot_id, "schema_version": snapshot.schema_version, "as_of": snapshot.as_of,
             "decision": snapshot.decision, "tradeable": snapshot.tradeable, "payload_hash": snapshot.payload_hash,
             "decision_trade_day": snapshot.decision_trade_day, "daybook_effective_day": snapshot.daybook_effective_day,
             "pulse_trade_day": snapshot.pulse_trade_day, "pulse_slot_closed_at": snapshot.pulse_slot_closed_at,
             "observed_at": snapshot.observed_at, "market_phase": snapshot.market_phase,
             "target_mode": snapshot.target_mode, "pending_eod_day": snapshot.pending_eod_day,
             "calendar_blocking_reason": snapshot.calendar_blocking_reason,
             "candidate_universe_id": candidate_universe.get("universe_id")}
            if snapshot else None
        ),
        history_db=_history_health(),
        llm=llm,
        serenity={
            **serenity,
            "snapshot_target_id": snapshot_target_id,
            "snapshot_readiness_revision": snapshot_readiness_revision,
            "active_readiness_revision": active_readiness_revision,
            "snapshot_semantic_revision": snapshot_semantic_revision,
            "active_semantic_revision": active_semantic_revision,
            "snapshot_native_ready": snapshot_native_ready,
            "snapshot_target_count": int(snapshot_serenity_policy.get("target_count") or 0),
            "snapshot_coverage_count": int(snapshot_serenity_policy.get("coverage_count") or 0),
            "snapshot_effective_weight": float(snapshot_serenity_policy.get("applied_weight") or 0.0),
            "snapshot_degraded_reason": snapshot_serenity_policy.get("failure_reason"),
        },
        candidate_universe=candidate_universe,
        worker={
            "publisher": "RecommendationSnapshot.v1",
            "selection_policy": "adaptive_v2_native_serenity_single_score",
            "runtime_contract_ready": runtime_contract_ready,
            "expected_market_time": runtime_contract,
        },
        llm_ready=llm.get("verification") == "ready",
        llm_retryable=bool(llm.get("configured")),
        storage=HealthStorageStats(
            session_count=int(health["sessions"]),
            transcript_count=int(health["turns"]),
            claim_count=int(health["claims"]),
            latest_session_at=(session_overviews[0]["updated_at"] if session_overviews else None),
        ),
        runtime=_workspace_runtime(store, snapshot),
    )


@router.get("/api/book/current", response_model=BookResponse)
def current_book() -> BookResponse:
    store = AgentStore()
    try:
        book = store.current_book()
    except StorageBusyError as ex:
        raise APIError(
            status_code=503,
            message="当前推荐快照读取繁忙",
            detail={"reason": str(ex), "retry_after_ms": ex.retry_after_ms},
        ) from ex
    return BookResponse(book=book.model_dump(mode="json") if book else {})


@router.get("/api/lunch/current", response_model=LunchResponse)
def current_lunch() -> LunchResponse:
    """Expose the completed morning session without conflating it with daily data."""
    store = AgentStore()
    try:
        book = store.current_book()
    except StorageBusyError as ex:
        raise APIError(
            status_code=503,
            message="午盘快照读取繁忙",
            detail={"reason": str(ex), "retry_after_ms": ex.retry_after_ms},
        ) from ex
    market_time = resolve_daily_target(allow_probe=False)
    phase = str(market_time.market_phase or "UNKNOWN")
    target_day = market_time.pulse_trade_day
    target_slot = market_time.pulse_slot_closed_at
    pulse_day = getattr(book, "pulse_trade_day", None) if book else None
    pulse_slot = getattr(book, "pulse_slot_at", None) if book else None
    slot_ok = str(getattr(book, "slot_status", "") or "").upper() == "OK"
    ready = bool(
        phase == "LUNCH_BREAK"
        and book is not None
        and target_day
        and pulse_day == target_day
        and target_slot
        and pulse_slot
        and str(pulse_slot) >= str(target_slot)
        and slot_ok
    )
    state = "READY" if ready else "PENDING" if phase == "LUNCH_BREAK" else "NOT_APPLICABLE"
    return LunchResponse(
        trade_day=target_day or market_time.decision_trade_day,
        market_phase=phase,
        state=state,
        generated_at=getattr(book, "updated_at", None) if book else None,
        session={
            "name": "morning_session",
            "target_closed_at": target_slot,
            "completed_at": pulse_slot if ready else None,
            "complete": ready,
        },
        daily={
            "effective_day": market_time.daybook_effective_day,
            "target_mode": market_time.target_mode,
            "today_complete": False,
        },
        market={
            "gate_state": getattr(getattr(book, "gate", None), "state", None),
            "gate_score": getattr(getattr(book, "gate", None), "score", None),
            "gate_reasons": list(getattr(getattr(book, "gate", None), "reasons", None) or []),
        },
    )


@router.get("/api/session/{session_id}", response_model=SessionResponse)
def session_view(session_id: str) -> SessionResponse:
    try:
        return SessionResponse(**_workspace_session_payload(AgentStore(), session_id))
    except StorageBusyError as ex:
        raise APIError(
            status_code=503,
            message="会话读取繁忙",
            detail={"reason": str(ex), "retry_after_ms": ex.retry_after_ms},
        ) from ex


@router.get("/api/session/{session_id}/diagnostics")
def session_diagnostics_view(session_id: str) -> dict[str, Any]:
    try:
        return _workspace_diagnostics(AgentStore(), session_id)
    except StorageBusyError as ex:
        raise APIError(
            status_code=503,
            message="会话诊断读取繁忙",
            detail={"reason": str(ex), "retry_after_ms": ex.retry_after_ms},
        ) from ex


@router.get("/api/sessions")
def session_overviews(limit: int = 20) -> list[dict[str, Any]]:
    try:
        return [
            {
                "session_id": row["session_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "title": str(row.get("title") or "新会话")[:40],
                "preview": str(row.get("preview") or "")[:120],
                "active_run_id": row.get("active_snapshot_id"),
            }
            for row in AgentStore().session_overviews(limit=limit)
        ]
    except StorageBusyError as ex:
        raise APIError(
            status_code=503,
            message="会话列表读取繁忙",
            detail={"reason": str(ex), "retry_after_ms": ex.retry_after_ms},
        ) from ex
