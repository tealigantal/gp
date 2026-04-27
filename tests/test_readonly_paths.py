from __future__ import annotations

from fastapi.testclient import TestClient

from gp_assistant.book import repo
from gp_assistant.contracts.objects import (
    DayBook,
    EvidencePack,
    Judgment,
    MarketBook,
    ReplyBundle,
    SessionState,
    TurnFrame,
)
from gp_assistant.gateway import routes
from gp_assistant.gateway.app import app
from gp_assistant.runtime import turn_loop


def _book() -> MarketBook:
    return MarketBook(
        trading_day="20240320",
        book_version="slot_artifact_1",
        updated_at="2024-03-20T10:00:00+08:00",
        regime={},
        daybook=DayBook(trading_day="20240320", generated_at="2024-03-20T09:00:00+08:00", regime={}),
        board=[],
        watchset=[],
        symbol_states={},
        portfolio_snapshot={},
        side_results=[],
        artifact_id="slot_artifact_1",
        slot_id="20240320_1000",
        slot_status="UNAVAILABLE",
        publish_allowed=False,
        daybook_effective_day="20240320",
        pulse_trade_day="20240320",
        pulse_slot_at="2024-03-20 10:00:00",
        market_phase="INTRADAY_AM",
        data_status="unavailable",
    )


def test_run_turn_sync_does_not_refresh_or_write(monkeypatch):
    book = _book()
    frame = TurnFrame(frame_id="f1", raw_message="现在怎么看", subject="market", request="chat", freshness="current_book")
    evidence = EvidencePack(frame=frame, session=SessionState(session_id="s1", created_at="t", updated_at="t"), book=book)
    judgment = Judgment(kind="chat", summary="readonly")
    reply = ReplyBundle(session_id="s1", text="readonly", kind="chat")

    monkeypatch.setattr(turn_loop, "load_current_book", lambda: book)
    monkeypatch.setattr(turn_loop, "parse_concern", lambda memory_ctx, loaded_book, user_message: frame)
    monkeypatch.setattr(turn_loop, "plan_evidence", lambda parsed_frame: {})
    monkeypatch.setattr(turn_loop, "build_evidence_pack", lambda frame, memory_ctx, loaded_book, plan, invalidate_active_run=False: evidence)
    monkeypatch.setattr(turn_loop, "make_judgment", lambda session_id, frame, evidence: judgment)
    monkeypatch.setattr(turn_loop, "build_reply", lambda session_id, frame, evidence, judgment, recent_turns=None: reply)
    monkeypatch.setattr(turn_loop, "validate_reply", lambda reply, judgment: None)
    monkeypatch.setattr(turn_loop, "commit_turn", lambda **kwargs: None)
    monkeypatch.setattr(repo, "save_current_pointer", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected write")))

    out = turn_loop.run_turn_sync(session_id="s1", user_message="现在怎么看")
    assert out["reply"] == "readonly"


def test_book_current_endpoint_does_not_write_pointer(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(routes, "load_current_book", lambda: _book())
    monkeypatch.setattr(repo, "save_current_pointer", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected write")))

    response = client.get("/api/book/current")
    assert response.status_code == 200
    assert response.json()["book"]["artifact_id"] == "slot_artifact_1"
