from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..contracts.objects import BoardEntry, EvidencePack, MarketBook, TurnFrame, ReplyBundle
from ..book.engine import ensure_book, load_current_book
from ..book.repo import load_run
from ..memory.service import load_memory_context, commit_turn
from .concern_parser import parse_concern
from .evidence_planner import plan_evidence
from .narrator import build_reply
from .grounding import validate_reply
from ..judgment.engine import make_judgment
from .reference_resolver import resolve_subject_and_compare
from .freshness_policy import make_refresh_plan, make_postclose_pending_plan
from ..evidence.market_service import probe_daybook_ready
from ..core.logging import logger


def _entry_by_symbol(book: MarketBook, symbol: str | None) -> BoardEntry | None:
    if not symbol:
        return None
    symbol = str(symbol).strip()
    for entry in book.board:
        if entry.symbol == symbol:
            return entry
    return None


def _entry_by_rank(entries: List[BoardEntry], rank: int | None) -> BoardEntry | None:
    if rank is None:
        return None
    for entry in entries:
        if entry.rank == rank:
            return entry
    return None


def _resolve_subject_entry(frame: TurnFrame, memory_ctx: Dict[str, Any], book: MarketBook, active_run, previous_run=None):
    session = memory_ctx['session']
    # Support history reference like "上一轮第二只": prefer previous_run picks when explicitly referenced
    raw = (frame.raw_message or '').strip()
    if ('上一轮' in raw or '上一次' in raw or '前一次' in raw) and previous_run is not None:
        active_entries = list(previous_run.picks)
    else:
        active_entries = list(active_run.picks) if active_run else list(book.board)
    return resolve_subject_and_compare(frame=frame, session=session, book=book, active_entries=active_entries)


def build_evidence_pack(frame: TurnFrame, memory_ctx: Dict[str, Any], book: MarketBook, plan: Dict[str, Any], *, invalidate_active_run: bool = False) -> EvidencePack:
    from ..evidence.validation_service import build_validation_slice
    from ..evidence.portfolio_service import load_portfolio_snapshot
    session = memory_ctx['session']
    active_run = None if invalidate_active_run else (load_run(session.active_run_id) if plan.get('need_active_run') else None)
    previous_run = load_run(session.previous_run_id) if plan.get('need_previous_run') else None
    subject_entry = None
    compare_entries: List[BoardEntry] = []
    if plan.get('need_subject_entry') or plan.get('need_compare_entries'):
        subject_entry, compare_entries = _resolve_subject_entry(frame, memory_ctx, book, active_run, previous_run)
    if plan.get('need_compare_entries') and not compare_entries:
        compare_entries = []
    strategy_id = None
    if subject_entry is not None:
        strategy_id = subject_entry.pick.strategy_id
    elif active_run and active_run.picks:
        strategy_id = active_run.picks[0].pick.strategy_id
    return EvidencePack(
        frame=frame,
        session=memory_ctx['session'],
        book=book,
        active_run=active_run,
        previous_run=previous_run,
        subject_entry=subject_entry,
        compare_entries=compare_entries,
        portfolio_slice=(load_portfolio_snapshot() if plan.get('need_portfolio') else {}),
        validation_slice=(build_validation_slice(strategy_id) if (plan.get('need_validation') and strategy_id) else {}),
        side_results=book.side_results,
        evidence_refs=[book.book_version],
    )


def run_turn_sync(session_id: str | None, user_message: str) -> Dict[str, Any]:
    session_id = session_id or 'default'
    memory_ctx = load_memory_context(session_id)
    # Pre-plan freshness using lightweight policy before full parse
    book0 = load_current_book()
    plan0 = make_refresh_plan(session=memory_ctx['session'], book=book0, user_message=user_message)
    try:
        logger.info(
            "[turn] preplan session=%s request_preview=%s phase=%s level=%s scope=%s target_day=%s pulse_day=%s slot=%s invalidate=%s",
            session_id,
            (user_message[:60] if isinstance(user_message, str) else str(user_message)),
            plan0.market_phase,
            plan0.level,
            plan0.scope,
            plan0.target_daybook_effective_day,
            plan0.target_pulse_trade_day,
            plan0.target_pulse_slot_at,
            plan0.invalidate_active_run,
        )
    except Exception:
        pass
    # Post-close pending: probe EOD readiness; if not ready, degrade plan to pending L0
    if plan0.market_phase == 'POSTCLOSE_PENDING':
        chk = probe_daybook_ready(plan0.target_daybook_effective_day)
        if not bool(chk.get('ready')):
            plan0 = make_postclose_pending_plan(book0)
    book = ensure_book(plan0)
    # Full parse on the refreshed book
    frame = parse_concern(memory_ctx, book, user_message)
    plan = plan_evidence(frame)
    evidence = build_evidence_pack(frame, memory_ctx, book, plan, invalidate_active_run=plan0.invalidate_active_run)
    judgment = make_judgment(session_id=session_id, frame=frame, evidence=evidence)
    reply = build_reply(
        session_id=session_id,
        frame=frame,
        evidence=evidence,
        judgment=judgment,
        recent_turns=memory_ctx.get('recent_turns') or [],
    )
    validate_reply(reply, judgment)
    commit_turn(session_id=session_id, user_message=user_message, reply=reply, judgment=judgment)
    try:
        logger.info(
            "[turn] completed session=%s kind=%s run_id=%s book=%s day=%s pulse_day=%s slot=%s phase=%s status=%s",
            session_id,
            (judgment.kind if hasattr(judgment, 'kind') else None),
            (reply.run_id if hasattr(reply, 'run_id') else None),
            book.book_version,
            getattr(book, 'daybook_effective_day', None) or book.daybook.trading_day,
            getattr(book, 'pulse_trade_day', None),
            getattr(book, 'pulse_slot_at', None),
            getattr(book, 'market_phase', None),
            getattr(book, 'data_status', None),
        )
    except Exception:
        pass
    return {
        'session_id': reply.session_id,
        'reply': reply.text,
        'message': reply.message,
        'run_id': reply.run_id,
        'symbols': reply.symbols,
        'right_panel': reply.right_panel,
        'ui_items': reply.ui_items,
        'planner_trace': reply.planner_trace,
        'evidence_refs': reply.evidence_refs,
    }


run_turn = run_turn_sync
