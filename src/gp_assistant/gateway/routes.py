from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ..agent_store import AgentStore, AgentStoreError, SnapshotIntegrityError
from ..chat_agent import run_chat_turn
from ..contracts.api import ChatHistoryResponse, ChatRequest, ChatResponse, HealthResponse
from ..core.errors import APIError
from ..search.history_store import history_db_path


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
    except AgentStoreError as ex:
        raise APIError(status_code=409, message="聊天写入被拒绝", detail={"reason": str(ex)}) from ex


@router.get("/api/chat/{session_id}", response_model=ChatHistoryResponse)
def chat_history(session_id: str) -> ChatHistoryResponse:
    turns = AgentStore().session_turns(session_id)
    if not turns:
        raise HTTPException(status_code=404, detail="session_not_found")
    return ChatHistoryResponse(session_id=session_id, turns=turns)


@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    store = AgentStore()
    stats = store.stats()
    snapshot = store.current_snapshot()
    return HealthResponse(
        status="ok",
        agent_db=stats,
        current_snapshot=(
            {"snapshot_id": snapshot.snapshot_id, "schema_version": snapshot.schema_version, "as_of": snapshot.as_of,
             "decision": snapshot.decision, "tradeable": snapshot.tradeable, "payload_hash": snapshot.payload_hash}
            if snapshot else None
        ),
        history_db=_history_health(),
        worker={"publisher": "RecommendationSnapshot.v1"},
    )
