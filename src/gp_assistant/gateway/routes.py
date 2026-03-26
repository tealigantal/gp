from __future__ import annotations

from fastapi import APIRouter

from ..contracts.api import ChatRequest, ChatResponse, HealthResponse, SessionResponse, BookResponse, RunResponse
from ..runtime.turn_loop import run_turn_sync
from ..gateway.queue import session_lane, book_lane
from ..gateway.sessions import get_session_payload
from ..gateway.events import list_side_results
from ..book.engine import ensure_book
from ..book.repo import load_current_book, load_run
from ..llm.client import LLMClient
from ..evidence.market_service import current_trading_day

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
    with book_lane():
        # Read-first: only rebuild when missing or trading day changes
        book = load_current_book()
        td = current_trading_day()
        if book is None or (getattr(book, 'trading_day', None) != td):
            book = ensure_book(force_rebuild=False)
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
