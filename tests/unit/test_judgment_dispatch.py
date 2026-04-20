from __future__ import annotations

from gp_assistant.judgment.engine import make_judgment
from gp_assistant.contracts.objects import TurnFrame


class DummyEvidence:
    book = object()  # not used for chat
    active_run = None
    previous_run = None
    subject_entry = None
    compare_entries = []
    portfolio_slice = {}
    validation_slice = {}
    side_results = []
    evidence_refs = []


def test_dispatch_chat_not_recommend(monkeypatch):
    called = {'recommend': 0}

    # Monkeypatch recommendation to count calls
    import gp_assistant.judgment.recommend as reco
    orig = reco.make_recommendation

    def fake_reco(*a, **k):
        called['recommend'] += 1
        return orig(*a, **k)

    monkeypatch.setattr(reco, 'make_recommendation', fake_reco)

    frame = TurnFrame(
        frame_id='f1', raw_message='hi', subject='run', request='chat', freshness='current_book',
        references={}, constraints={}, ambiguity={'confidence': 0.9, 'notes': []},
    )
    j = make_judgment('s1', frame, DummyEvidence())
    assert j.kind == 'chat'
    assert called['recommend'] == 0


def test_unhandled_request_raises():
    # explain for symbol/pick without subject_entry should raise
    frame = TurnFrame(
        frame_id='f2', raw_message='why', subject='symbol', request='explain', freshness='current_book',
        references={}, constraints={}, ambiguity={'confidence': 0.9, 'notes': []},
    )
    try:
        _ = make_judgment('s1', frame, DummyEvidence())
        assert False, 'should raise'
    except ValueError:
        assert True
