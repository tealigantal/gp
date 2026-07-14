from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ..agent_store import AgentStore, AgentStoreError, SnapshotIntegrityError, StorageBusyError
from ..chat_agent import _current_serenity_check, run_chat_turn
from ..contracts.api import ChatHistoryResponse, ChatRequest, ChatResponse, HealthResponse
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


router = APIRouter()


def _history_health() -> dict[str, Any]:
    path = history_db_path()
    return {"path": str(path), "exists": path.exists(), "bytes": path.stat().st_size if path.exists() else 0}


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
            snapshot_target_id = str(source_meta.get("serenity_target_id") or "") or None
            snapshot_readiness_revision = str(
                source_meta.get("serenity_readiness_revision") or ""
            ) or None
            snapshot_semantic_revision = str(
                source_meta.get("serenity_semantic_revision") or ""
            ) or None
            pending_snapshot = not (
                source_meta.get("serenity_native_ready") is True
                or bool(book.daybook.picks)
            )
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
                if pending_snapshot:
                    readiness_reasons.append(
                        "当前推荐快照仍在等待 Serenity 原生候选完整覆盖"
                    )
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
                if serenity_reason:
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
                    not pending_snapshot
                    and runtime_contract_ready
                    and serenity_reason is None
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
             "calendar_blocking_reason": snapshot.calendar_blocking_reason}
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
        },
        worker={
            "publisher": "RecommendationSnapshot.v1",
            "selection_policy": "adaptive_v2_native_serenity_single_score",
            "runtime_contract_ready": runtime_contract_ready,
            "expected_market_time": runtime_contract,
        },
    )
