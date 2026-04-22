from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ..contracts.objects import BoardEntry, MarketBook


def _entry_by_symbol(entries: List[BoardEntry], symbol: str | None) -> BoardEntry | None:
    if not symbol:
        return None
    symbol = str(symbol).strip()
    for e in entries:
        if e.symbol == symbol:
            return e
    return None


def _entry_by_rank(entries: List[BoardEntry], rank: int | None) -> BoardEntry | None:
    if rank is None:
        return None
    for e in entries:
        if e.rank == rank:
            return e
    return None


def resolve_subject_and_compare(
    *,
    frame,
    session,
    book: MarketBook,
    active_entries: List[BoardEntry],
) -> Tuple[BoardEntry | None, List[BoardEntry]]:
    refs = frame.references or {}
    subject_entry: BoardEntry | None = None
    # 1) prefer active_run.picks then fallback to board for symbol
    if isinstance(refs.get('symbol'), str):
        subject_entry = _entry_by_symbol(active_entries, refs.get('symbol')) or _entry_by_symbol(book.board, refs.get('symbol'))
    # 2) rank within active entries
    if subject_entry is None and refs.get('rank') is not None:
        try:
            subject_entry = _entry_by_rank(active_entries, int(refs.get('rank')))
        except Exception:
            subject_entry = None
    # 3) fallback to session focus symbol
    if subject_entry is None and isinstance(session.focus_subject, dict):
        if session.focus_subject.get('type') == 'symbol':
            subject_entry = _entry_by_symbol(active_entries, session.focus_subject.get('symbol')) or _entry_by_symbol(book.board, session.focus_subject.get('symbol'))

    compare_entries: List[BoardEntry] = []
    # Unify compare set: prefer explicit compare_symbols, else symbols, else session.compare_set
    compare_symbols = []
    if isinstance(refs.get('compare_symbols'), list) and refs.get('compare_symbols'):
        compare_symbols = refs.get('compare_symbols')
    elif isinstance(refs.get('symbols'), list) and refs.get('symbols'):
        compare_symbols = refs.get('symbols')
    elif isinstance(session.compare_set, list) and session.compare_set:
        compare_symbols = session.compare_set
    if compare_symbols:
        want = set(str(s).strip() for s in compare_symbols if str(s).strip())
        compare_entries = [e for e in (active_entries or book.board) if e.symbol in want]
    if subject_entry and not compare_entries and frame.request == 'compare':
        compare_entries = [subject_entry] + [e for e in book.board if e.symbol != subject_entry.symbol][:1]
    return subject_entry, compare_entries
