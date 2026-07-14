from __future__ import annotations

from types import SimpleNamespace

from gp_assistant.contracts.objects import DayBook, MarketBook
from gp_assistant.runtime.market_time import MarketTimeContext
from gp_assistant.runtime.market_clock import PHASE_POSTCLOSE_PENDING, PHASE_PREOPEN
import gp_assistant.worker as worker


def _context(*, mode: str = "previous_completed") -> MarketTimeContext:
    return MarketTimeContext(
        decision_trade_day="2026-07-13", daybook_effective_day="2026-07-10", pulse_trade_day="2026-07-13",
        pulse_slot_closed_at=None, observed_at="2026-07-13T08:00:00+08:00", market_phase=PHASE_PREOPEN,
        target_mode=mode, pending_eod_day="2026-07-13" if mode == "current_pending" else None,
    )


def _ready_source_meta() -> dict:
    return {
        "serenity_native_ready": True,
        "serenity_target_id": "target-1",
        "serenity_formula_version": "adaptive_v2_native_serenity.v1",
        "serenity_source_run_id": "poll-1",
        "serenity_readiness_revision": "revision-old",
        "serenity_semantic_revision": "semantic-old",
        "serenity_poll_finished_at": "2026-07-13T07:55:00+08:00",
        "serenity_poll_expires_at": "2026-07-13T09:00:00+08:00",
        "serenity_candidate_target": {
            "input_hash": "target-hash",
            "activation_observed_at": "2026-07-13T07:00:00+08:00",
            "activation_revision": "activation-1",
        },
        "serenity_policy_snapshot": {
            "mode": "native",
            "state": "shadow",
            "epoch": 1,
            "applied_weight": 0.0,
            "max_weight": 0.08,
            "native_required": True,
        },
    }


def _current_binding(**updates) -> dict:
    binding = {
        "mode": "native",
        "formula_version": "adaptive_v2_native_serenity.v1",
        "target_id": "target-1",
        "target_input_hash": "target-hash",
        "activation_observed_at": "2026-07-13T07:00:00+08:00",
        "activation_revision": "activation-1",
        "source_run_id": "poll-1",
        "readiness_revision": "revision-old",
        "semantic_revision": "semantic-old",
        "poll_finished_at": "2026-07-13T07:55:00+08:00",
        "poll_expires_at": "2026-07-13T09:00:00+08:00",
        "policy_state": "shadow",
        "policy_epoch": 1,
        "policy_applied_weight": 0.0,
        "policy_max_weight": 0.08,
        "native_required": True,
        "target_matches": True,
        "certificate_current": True,
        "available": True,
    }
    binding.update(updates)
    return binding


def test_daybook_build_uses_completed_daily_bar_day_without_prepublish_cache(
    monkeypatch,
):
    context = _context()
    built: list[str] = []
    saved: list[DayBook] = []

    class Store:
        def load_daybook(self, *_args, **_kwargs):
            return None

        def save_daybook(self, daybook):
            saved.append(daybook)

    monkeypatch.setattr(worker, "AgentStore", Store)
    monkeypatch.setattr(worker, "build_daybook", lambda day, **_: built.append(day) or DayBook(trading_day=day, generated_at="2026-07-13T08:00:00+08:00", producer=worker.producer_metadata()))

    result = worker._load_or_build_daybook(context)

    assert built == ["20260710"]
    assert result.trading_day == "20260710"
    assert saved == []


def test_second_loop_reuses_immutable_producer_compatible_daybook(monkeypatch):
    context = _context()
    daybook = DayBook(trading_day="20260710", generated_at="2026-07-13T08:00:00+08:00", producer=worker.producer_metadata())

    class Store:
        def load_daybook(self, effective_day, **_kwargs):
            assert effective_day == "2026-07-10"
            return daybook

    monkeypatch.setattr(worker, "AgentStore", Store)
    monkeypatch.setattr(worker, "build_daybook", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not rebuild")))

    assert worker._load_or_build_daybook(context) is daybook


def test_ready_daybook_reuses_when_same_semantics_get_a_new_freshness_certificate(
    monkeypatch,
):
    context = _context()
    stored = DayBook(
        trading_day="20260710",
        generated_at="2026-07-13T08:00:00+08:00",
        producer=worker.producer_metadata(),
        source_meta=_ready_source_meta(),
    )
    class Store:
        def load_daybook(self, *_args, **_kwargs):
            return stored

    monkeypatch.setattr(worker, "AgentStore", Store)
    monkeypatch.setattr(
        worker,
        "current_native_readiness_state",
        lambda *_args, **_kwargs: _current_binding(
            source_run_id="poll-2",
            readiness_revision="revision-new",
            poll_finished_at="2026-07-13T07:57:00+08:00",
            poll_expires_at="2026-07-13T09:02:00+08:00",
        ),
    )
    monkeypatch.setattr(
        worker,
        "build_daybook",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("freshness-only renewal must not rebuild")
        ),
    )

    result = worker._load_or_build_daybook(context)

    assert result is stored


def test_ready_daybook_rebuilds_when_serenity_semantics_change(monkeypatch):
    context = _context()
    stored = DayBook(
        trading_day="20260710",
        generated_at="2026-07-13T08:00:00+08:00",
        producer=worker.producer_metadata(),
        source_meta=_ready_source_meta(),
    )
    built = DayBook(
        trading_day="20260710",
        generated_at="2026-07-13T08:01:00+08:00",
        producer=worker.producer_metadata(),
    )

    class Store:
        def load_daybook(self, *_args, **_kwargs):
            return stored

    monkeypatch.setattr(worker, "AgentStore", Store)
    monkeypatch.setattr(
        worker,
        "current_native_readiness_state",
        lambda *_args, **_kwargs: _current_binding(
            semantic_revision="semantic-new"
        ),
    )
    monkeypatch.setattr(worker, "build_daybook", lambda *_args, **_kwargs: built)

    assert worker._load_or_build_daybook(context) is built


def test_ready_daybook_rebuilds_when_policy_changes_without_a_new_poll(
    monkeypatch,
):
    context = _context()
    stored = DayBook(
        trading_day="20260710",
        generated_at="2026-07-13T08:00:00+08:00",
        producer=worker.producer_metadata(),
        source_meta=_ready_source_meta(),
    )
    built = DayBook(
        trading_day="20260710",
        generated_at="2026-07-13T08:01:00+08:00",
        producer=worker.producer_metadata(),
    )

    class Store:
        def load_daybook(self, *_args, **_kwargs):
            return stored

    monkeypatch.setattr(worker, "AgentStore", Store)
    monkeypatch.setattr(
        worker,
        "current_native_readiness_state",
        lambda *_args, **_kwargs: _current_binding(
            policy_state="probation",
            policy_epoch=2,
            policy_applied_weight=0.02,
        ),
    )
    monkeypatch.setattr(worker, "build_daybook", lambda *_args, **_kwargs: built)

    assert worker._load_or_build_daybook(context) is built


def test_pending_daybook_without_a_target_is_never_reused(monkeypatch):
    context = _context()
    pending = DayBook(
        trading_day="20260710",
        generated_at="2026-07-13T08:00:00+08:00",
        producer=worker.producer_metadata(),
        source_meta={"serenity_native_ready": False},
    )
    built = DayBook(
        trading_day="20260710",
        generated_at="2026-07-13T08:01:00+08:00",
        producer=worker.producer_metadata(),
    )

    class Store:
        def load_daybook(self, *_args, **_kwargs):
            return pending

    monkeypatch.setattr(worker, "AgentStore", Store)
    monkeypatch.setattr(worker, "build_daybook", lambda *_args, **_kwargs: built)

    assert worker._load_or_build_daybook(context) is built


def test_snapshot_noop_requires_the_exact_rebuilt_native_daybook():
    pending = DayBook(
        trading_day="20260710",
        generated_at="2026-07-13T08:00:00+08:00",
        producer=worker.producer_metadata(),
        source_meta={"serenity_target_id": "target-1", "serenity_native_ready": False},
    )
    ready = pending.model_copy(
        update={
            "generated_at": "2026-07-13T08:01:00+08:00",
            "source_meta": {
                "serenity_target_id": "target-1",
                "serenity_native_ready": True,
            },
        }
    )
    published = MarketBook(
        trading_day="20260710",
        book_version="pending",
        artifact_id="pending",
        updated_at="2026-07-13T08:00:00+08:00",
        regime={},
        daybook=pending,
        board=[],
        publish_allowed=False,
    )
    snapshot = SimpleNamespace(payload={"book": published.model_dump(mode="json")})

    assert worker._snapshot_contains_daybook(snapshot, pending) is True
    assert worker._snapshot_contains_daybook(snapshot, ready) is False


def test_snapshot_noop_requires_exact_market_phase_and_pulse_contract():
    context = _context()
    snapshot = SimpleNamespace(
        decision_trade_day=context.decision_trade_day,
        daybook_effective_day=context.daybook_effective_day,
        pulse_trade_day=context.pulse_trade_day,
        pulse_slot_closed_at=context.pulse_slot_closed_at,
        market_phase=context.market_phase,
        target_mode=context.target_mode,
        pending_eod_day=context.pending_eod_day,
        calendar_blocking_reason=context.calendar_blocking_reason,
    )

    assert worker._snapshot_matches_market_time(snapshot, context) is True
    snapshot.market_phase = PHASE_POSTCLOSE_PENDING
    assert worker._snapshot_matches_market_time(snapshot, context) is False
    snapshot.market_phase = context.market_phase
    snapshot.pulse_trade_day = "2026-07-10"
    assert worker._snapshot_matches_market_time(snapshot, context) is False
    snapshot.pulse_trade_day = context.pulse_trade_day
    snapshot.calendar_blocking_reason = "calendar_source_unavailable"
    assert worker._snapshot_matches_market_time(snapshot, context) is False


def test_pending_eod_does_not_build_or_advance_snapshot(monkeypatch):
    context = _context(mode="current_pending")
    state = SimpleNamespace(market_phase=PHASE_POSTCLOSE_PENDING)
    monkeypatch.setattr(worker, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(worker, "resolve_daily_target", lambda **_kwargs: context)
    monkeypatch.setattr(worker, "_load_or_build_daybook", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("pending eod must not select")))

    result = worker.run_runtime_chain()

    assert result["pending"] is True
    assert result["runtime_stage"] == "probing_eod"
    assert result["decision_trade_day"] == "2026-07-13"
    assert result["daybook_effective_day"] == "2026-07-10"
