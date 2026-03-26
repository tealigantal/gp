from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..contracts.objects import BoardEntry, EvidencePack, MarketBook, TurnFrame, ReplyBundle
from ..book.engine import ensure_book
from ..book.repo import load_run
from ..memory.service import load_memory_context, commit_turn
from .concern_parser import parse_concern
from .evidence_planner import plan_evidence
from .narrator import build_reply
from .grounding import validate_reply
from ..judgment.engine import make_judgment


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


def _resolve_subject_entry(frame: TurnFrame, memory_ctx: Dict[str, Any], book: MarketBook):
    refs = frame.references or {}
    session = memory_ctx['session']
    active_run = load_run(session.active_run_id)
    previous_run = load_run(session.previous_run_id)
    active_entries = list(active_run.picks) if active_run else list(book.board)
    subject_entry = None
    if isinstance(refs.get('symbol'), str):
        subject_entry = _entry_by_symbol(book, refs.get('symbol'))
    if subject_entry is None and refs.get('rank') is not None:
        try:
            subject_entry = _entry_by_rank(active_entries, int(refs.get('rank')))
        except Exception:
            subject_entry = None
    if subject_entry is None and isinstance(session.focus_subject, dict):
        if session.focus_subject.get('type') == 'symbol':
            subject_entry = _entry_by_symbol(book, session.focus_subject.get('symbol'))
    compare_entries: List[BoardEntry] = []
    compare_symbols = refs.get('symbols') or session.compare_set or []
    if isinstance(compare_symbols, list):
        compare_entries = [e for e in book.board if e.symbol in set(str(s) for s in compare_symbols)]
    if subject_entry and not compare_entries and frame.request == 'compare':
        compare_entries = [subject_entry] + [e for e in book.board if e.symbol != subject_entry.symbol][:1]
    return active_run, previous_run, subject_entry, compare_entries


def build_evidence_pack(frame: TurnFrame, memory_ctx: Dict[str, Any], book: MarketBook) -> EvidencePack:
    from ..evidence.validation_service import build_validation_slice
    from ..evidence.portfolio_service import load_portfolio_snapshot
    active_run, previous_run, subject_entry, compare_entries = _resolve_subject_entry(frame, memory_ctx, book)
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
        portfolio_slice=load_portfolio_snapshot(),
        validation_slice=build_validation_slice(strategy_id),
        side_results=book.side_results,
        evidence_refs=[book.book_version],
    )


def run_turn_sync(session_id: str | None, user_message: str) -> Dict[str, Any]:
    session_id = session_id or 'default'
    book = ensure_book(force_rebuild=False)
    memory_ctx = load_memory_context(session_id)
    frame = parse_concern(memory_ctx, book, user_message)
    evidence = build_evidence_pack(frame, memory_ctx, book)
    judgment = make_judgment(session_id=session_id, frame=frame, evidence=evidence)
    reply = build_reply(session_id=session_id, frame=frame, evidence=evidence, judgment=judgment)
    validate_reply(reply, judgment)
    commit_turn(session_id=session_id, user_message=user_message, reply=reply, judgment=judgment)
    return {
        'session_id': reply.session_id,
        'reply': reply.text,
        'run_id': reply.run_id,
        'symbols': reply.symbols,
        'right_panel': reply.right_panel,
        'ui_items': reply.ui_items,
        'planner_trace': reply.planner_trace,
        'evidence_refs': reply.evidence_refs,
    }


run_turn = run_turn_sync
