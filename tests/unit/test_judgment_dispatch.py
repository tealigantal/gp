from __future__ import annotations

from gp_assistant.contracts.objects import DayBook, MarketBook, SessionState, TurnFrame
from gp_assistant.judgment.engine import make_judgment
from gp_assistant.runtime.utils import now_iso


def _book() -> MarketBook:
    db = DayBook(trading_day="20260101", generated_at=now_iso(), tradeable=True)
    return MarketBook(
        trading_day="20260101",
        book_version="v1",
        updated_at=now_iso(),
        daybook=db,
        board=[],
        watchset=[],
        symbol_states={},
        portfolio_snapshot={},
        side_results=[],
        market_phase="NON_TRADING",
        slot_status="UNAVAILABLE",
        publish_allowed=False,
    )


class DummyEvidence:
    def __init__(self):
        self.book = _book()
        self.active_run = None
        self.previous_run = None
        self.subject_entry = None
        self.compare_entries = []
        self.portfolio_slice = {}
        self.validation_slice = {}
        self.side_results = []
        self.evidence_refs = []
        self.session = SessionState(session_id="s1", created_at=now_iso(), updated_at=now_iso())


def test_dispatch_chat_not_recommend():
    frame = TurnFrame(
        frame_id="f1",
        raw_message="hi",
        subject="run",
        request="chat",
        freshness="active_run",
        references={},
        constraints={},
        ambiguity={"confidence": 0.9, "notes": []},
    )
    j = make_judgment("s1", frame, DummyEvidence())
    assert j.kind == "chat"


def test_pick_detail_without_subject_returns_no_trade():
    frame = TurnFrame(
        frame_id="f2",
        raw_message="why",
        subject="symbol",
        request="pick_detail",
        freshness="active_run",
        references={},
        constraints={},
        ambiguity={"confidence": 0.9, "notes": []},
    )
    j = make_judgment("s1", frame, DummyEvidence())
    assert j.kind == "no_trade"
    assert j.no_trade is not None
