from __future__ import annotations

from typing import Any, Dict, List

from ..book.engine import load_current_book, sync_book_once
from ..book.repo import load_run
from ..contracts.objects import BoardEntry, EvidencePack, MarketBook, ReplyBundle, TurnFrame
from ..core.logging import logger
from ..judgment.engine import make_judgment
from ..memory.service import commit_turn, load_memory_context
from .concern_parser import parse_concern
from .evidence_planner import plan_evidence
from .grounding import validate_reply
from .narrator import build_reply
from .reference_resolver import resolve_subject_and_compare


def _resolve_subject_entry(frame: TurnFrame, memory_ctx: Dict[str, Any], book: MarketBook, active_run, previous_run=None):
    session = memory_ctx["session"]
    raw = (frame.raw_message or "").strip()
    history_requested = any(token in raw for token in ("上一轮", "上次", "之前", "历史"))
    active_entries = list(previous_run.picks) if history_requested and previous_run is not None else (list(active_run.picks) if active_run else list(book.board))
    return resolve_subject_and_compare(frame=frame, session=session, book=book, active_entries=active_entries)


def build_evidence_pack(frame: TurnFrame, memory_ctx: Dict[str, Any], book: MarketBook, plan: Dict[str, Any], *, invalidate_active_run: bool = False) -> EvidencePack:
    from ..evidence.portfolio_service import load_portfolio_snapshot
    from ..evidence.validation_service import build_validation_slice

    session = memory_ctx["session"]
    active_run = None if invalidate_active_run else (load_run(session.active_run_id) if plan.get("need_active_run") else None)
    previous_run = load_run(session.previous_run_id) if plan.get("need_previous_run") else None
    subject_entry = None
    compare_entries: List[BoardEntry] = []
    if plan.get("need_subject_entry") or plan.get("need_compare_entries"):
        subject_entry, compare_entries = _resolve_subject_entry(frame, memory_ctx, book, active_run, previous_run)
    strategy_id = None
    if subject_entry is not None:
        strategy_id = subject_entry.pick.strategy_id
    elif active_run and active_run.picks:
        strategy_id = active_run.picks[0].pick.strategy_id
    return EvidencePack(
        frame=frame,
        session=memory_ctx["session"],
        book=book,
        active_run=active_run,
        previous_run=previous_run,
        subject_entry=subject_entry,
        compare_entries=compare_entries,
        portfolio_slice=(load_portfolio_snapshot() if plan.get("need_portfolio") else {}),
        validation_slice=(build_validation_slice(strategy_id) if (plan.get("need_validation") and strategy_id) else {}),
        side_results=book.side_results,
        evidence_refs=[book.book_version],
    )


def run_turn_sync(session_id: str | None, user_message: str) -> Dict[str, Any]:
    session_id = session_id or "default"
    memory_ctx = load_memory_context(session_id)
    sync_book_once()
    book = load_current_book()
    if book is None:
        raise RuntimeError("current book unavailable")
    try:
        logger.info(
            "[turn] load session=%s request=%s book=%s day=%s pulse_day=%s slot=%s phase=%s status=%s",
            session_id,
            (user_message[:60] if isinstance(user_message, str) else str(user_message)),
            book.book_version,
            book.daybook_effective_day or book.daybook.trading_day,
            book.pulse_trade_day,
            book.pulse_slot_at,
            book.market_phase,
            book.data_status,
        )
    except Exception:
        pass

    frame = parse_concern(memory_ctx, book, user_message)
    plan = plan_evidence(frame)
    evidence = build_evidence_pack(frame, memory_ctx, book, plan, invalidate_active_run=False)
    judgment = make_judgment(session_id=session_id, frame=frame, evidence=evidence)
    reply = build_reply(
        session_id=session_id,
        frame=frame,
        evidence=evidence,
        judgment=judgment,
        recent_turns=memory_ctx.get("recent_turns") or [],
    )
    validate_reply(reply, judgment)
    commit_turn(session_id=session_id, user_message=user_message, reply=reply, judgment=judgment)
    return {
        "session_id": reply.session_id,
        "reply": reply.text,
        "message": reply.message,
        "run_id": reply.run_id,
        "symbols": reply.symbols,
        "right_panel": reply.right_panel,
        "ui_items": reply.ui_items,
        "planner_trace": reply.planner_trace,
        "evidence_refs": reply.evidence_refs,
    }


run_turn = run_turn_sync
