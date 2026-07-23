from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from ..application.conversation_service import ConversationService
from ..store import ContractStore, ContractStoreError, UnsupportedDatabaseSchema
from ..application.real_producer import RealRecommendationProducer
from ..application.runtime_producer import RuntimeRecommendationProducer
from ..contracts.conversation import ConversationSession, ConversationTurn


router = APIRouter()


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    session_id: str | None = None
    client_turn_id: str
    message: str


class ConversationSessionResponse(BaseModel):
    session: ConversationSession
    turns: list[ConversationTurn]


@router.get("/api/recommendation/current")
def current_recommendation() -> dict[str, object]:
    publication = ContractStore().current_publication()
    if publication is None:
        raise HTTPException(status_code=404, detail="publication_not_found")
    return publication.model_dump(mode="json")


@router.post("/api/recommendation/refresh")
def refresh_recommendation() -> dict[str, object]:
    command = RealRecommendationProducer(ContractStore()).produce(datetime.now(ZoneInfo("Asia/Shanghai")))
    return command.plan.model_dump(mode="json")


@router.post("/api/recommendation/runtime/refresh")
def refresh_runtime() -> dict[str, object]:
    runtime = RuntimeRecommendationProducer(ContractStore()).produce(now=datetime.now(ZoneInfo("Asia/Shanghai")))
    return runtime.model_dump(mode="json")


@router.get("/api/lunch/current")
def current_lunch() -> dict[str, object]:
    publication = ContractStore().current_publication()
    if publication is None:
        raise HTTPException(status_code=404, detail="publication_not_found")
    runtime = ContractStore().load_runtime(publication.runtime_id) if publication.runtime_id else None
    return {
        "market_session_date": ContractStore().load_plan(publication.plan_id).market_session_date if ContractStore().load_plan(publication.plan_id) else None,
        "plan_id": publication.plan_id,
        "runtime_id": publication.runtime_id,
        "publication_id": publication.publication_id,
        "morning_slot_closed_at": runtime.slot_closed_at if runtime else None,
        "morning_session_state": runtime.market_phase if runtime else "pending",
        "tradeable_now": publication.decision.tradeable_now,
        "reason_codes": publication.decision.reason_codes,
    }


@router.get("/api/health")
def health() -> dict[str, str | None]:
    return ContractStore().health()


@router.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, object]:
    try:
        return ConversationService(ContractStore()).reply(session_id=request.session_id, client_turn_id=request.client_turn_id, user_message=request.message)
    except ContractStoreError as exc:
        reason = str(exc)
        status = 409 if reason in {"conversation_deleted", "session_publication_mismatch"} else 500
        raise HTTPException(status_code=status, detail=reason) from exc
    except ValueError as exc:
        reason = str(exc)
        status = 503 if reason.startswith("narration_unavailable") else 404 if reason == "publication_not_found" else 409
        raise HTTPException(status_code=status, detail=reason) from exc


@router.get("/api/conversations")
def list_conversations(limit: int = 20) -> list[ConversationSession]:
    return ContractStore().list_conversation_sessions(limit=limit)


@router.get("/api/conversations/{session_id}")
def read_conversation(session_id: str) -> ConversationSessionResponse:
    stored = ContractStore().read_conversation_session(session_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    session, turns = stored
    return ConversationSessionResponse(session=session, turns=turns)


@router.delete("/api/conversations/{session_id}", status_code=204)
def delete_conversation(session_id: str) -> Response:
    if not ContractStore().delete_conversation_session(session_id):
        raise HTTPException(status_code=404, detail="conversation_not_found")
    return Response(status_code=204)


@router.get("/api/contract/time")
def contract_time() -> dict[str, str]:
    return {"generated_at": datetime.now(UTC).isoformat()}
