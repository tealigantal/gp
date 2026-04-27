from __future__ import annotations

from gp_assistant.contracts.objects import TurnFrame
from gp_assistant.judgment.engine import make_judgment


class DummyEvidence:
    book = object()
    active_run = None
    previous_run = None
    subject_entry = None
    compare_entries = []
    portfolio_slice = {}
    validation_slice = {}
    side_results = []
    evidence_refs = []
    session = type("Session", (), {"session_id": "s1"})()


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


def test_unhandled_pick_detail_without_subject_raises():
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
    try:
        make_judgment("s1", frame, DummyEvidence())
        assert False, "should raise"
    except ValueError:
        assert True
