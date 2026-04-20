from __future__ import annotations

from fastapi import APIRouter

from ..contracts.api import ChatRequest, ChatResponse, HealthResponse, SessionResponse, BookResponse, RunResponse
from ..runtime.turn_loop import run_turn_sync
from ..gateway.queue import session_lane, book_lane
from ..gateway.sessions import get_session_payload
from ..memory.session_store import list_sessions
from ..memory.transcript_store import load_recent
from ..gateway.events import list_side_results
from ..book.engine import ensure_book, load_current_book
from ..book.repo import load_current_book, load_run
from ..llm.client import LLMClient
from ..evidence.market_service import current_trading_day
from ..runtime.freshness_policy import make_refresh_plan, make_dashboard_refresh_plan
from ..memory.session_store import default_session

router = APIRouter()


@router.post('/chat', response_model=ChatResponse)
@router.post('/api/chat', response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or 'default'
    with session_lane(session_id):
        out = run_turn_sync(session_id=session_id, user_message=req.message)
    return ChatResponse(**out)


@router.get('/health', response_model=HealthResponse)
@router.get('/api/health', response_model=HealthResponse)
def health() -> HealthResponse:
    book = load_current_book()
    ok, _ = LLMClient().available()
    return HealthResponse(status='ok', trading_day=current_trading_day(), book_version=(book.book_version if book else None), llm_ready=ok)


@router.get('/api/book/current', response_model=BookResponse)
def current_book() -> BookResponse:
    # Always advance to latest 5m pulse on fetch (cheap, rebuilds daybook only when day changes)
    with book_lane():
        # dashboard/book endpoint should not rely on empty-message plan; use dashboard plan
        plan = make_dashboard_refresh_plan()
        book = ensure_book(plan)
    return BookResponse(book=book.model_dump())


@router.get('/api/run/{run_id}', response_model=RunResponse)
def get_run(run_id: str) -> RunResponse:
    run = load_run(run_id)
    return RunResponse(run=run.model_dump() if run else {})


@router.get('/api/session/{session_id}', response_model=SessionResponse)
def get_session(session_id: str) -> SessionResponse:
    return SessionResponse(**get_session_payload(session_id))


@router.get('/api/side-results')
def side_results() -> list[dict]:
    return list_side_results()


@router.get('/api/sessions')
def list_session_overviews(limit: int = 20) -> list[dict]:
    out: list[dict] = []
    for s in list_sessions(limit=limit):
        turns = load_recent(s.session_id, limit=4)
        title = None
        preview = None
        for t in reversed(turns):
            if t.role == 'assistant' and not preview:
                preview = t.content[:120]
            if t.role == 'user' and not title:
                title = t.content[:40]
        out.append({
            'session_id': s.session_id,
            'created_at': s.created_at,
            'updated_at': s.updated_at,
            'title': title or '对话',
            'preview': preview or '',
            'active_run_id': s.active_run_id,
        })
    return out
