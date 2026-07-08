from __future__ import annotations

from ..book.repo import save_run
from ..contracts.objects import AdviceRun, MarketBook
from ..evidence.daily_freshness import active_freshness_for_current_target
from ..runtime.canonical_artifact import build_canonical_run
from ..runtime.utils import gen_id, now_iso


def publish_run(session_id: str, book: MarketBook, topk: int = 3) -> AdviceRun:
    book_day = book.daybook_effective_day or book.daybook.trading_day
    raw_freshness = dict(book.daybook.source_meta.get("daily_freshness") or {})
    freshness = active_freshness_for_current_target(
        raw_freshness,
        book_day=book_day,
    )
    stale_freshness_discarded = bool(raw_freshness) and not freshness
    freshness_ready = bool(freshness.get("ready", True))
    picks = list(book.board[:topk]) if freshness_ready else []
    run = AdviceRun(
        run_id=gen_id("run"),
        session_id=session_id,
        book_version=book.book_version,
        created_at=now_iso(),
        trading_day=book.trading_day,
        regime=book.regime,
        tradeable=bool(book.daybook.tradeable and freshness_ready),
        reason=(
            freshness.get("blocking_reason")
            if not freshness_ready
            else (None if stale_freshness_discarded else book.daybook.reason) or book.data_status
        ),
        picks=picks,
        evidence_refs=[book.book_version, *([book.artifact_id] if book.artifact_id else [])],
        artifact_id=book.artifact_id,
        slot_id=book.slot_id,
        slot_status=book.slot_status,
        publish_allowed=book.publish_allowed,
        daybook_effective_day=book.daybook_effective_day or book.daybook.trading_day,
        pulse_trade_day=book.pulse_trade_day,
        pulse_slot_at=book.pulse_slot_at,
        market_phase=book.market_phase,
        data_status=book.data_status,
        non_trading=False,
        data_quality=book.data_quality.model_dump(),
        data_provenance={
            "provider": book.data_quality.provider,
            "artifact_id": book.artifact_id,
            "book_version": book.book_version,
            "slot_status": book.slot_status,
            "pulse_slot_at": book.pulse_slot_at,
            "decision_context_snapshot_id": (
                book.daybook.source_meta.get("decision_context_snapshot_id")
                if isinstance(book.daybook.source_meta, dict)
                else None
            ),
        },
        gate_state=book.gate.state,
        gate_reasons=list(book.gate.reasons or []),
    )
    canonical = build_canonical_run(book=book, run=run, picks=picks)
    run.run_action = canonical.run_action
    run.recommendation_state = canonical.recommendation_state
    run.non_trading = canonical.non_trading
    run.status_reason = canonical.status_reason
    run.no_trade_reasons = list(canonical.no_trade_reasons)
    run.recovery_conditions = list(canonical.recovery_conditions)
    run.data_quality = dict(canonical.data_quality)
    run.data_provenance = dict(canonical.data_provenance)
    run.explain_context = dict(canonical.explain_context)
    run.decision_evidence_pack = dict(canonical.decision_evidence_pack)
    run.decision_context_snapshot_id = canonical.decision_context_snapshot_id
    save_run(run)
    return run
