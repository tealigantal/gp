from __future__ import annotations

import re
from typing import Dict, List, Tuple

from ..contracts.objects import BoardEntry, MarketBook, TurnFrame

_SYMBOL_RE = re.compile(r"(?<!\d)(?:60|68|00|30)\d{4}(?!\d)")
_RANK_RE = re.compile(r"第\s*(\d{1,2})\s*(?:只|个|支)?")


def _entry_by_symbol(entries: List[BoardEntry], symbol: str | None) -> BoardEntry | None:
    if not symbol:
        return None
    symbol = str(symbol).strip()
    for entry in entries:
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


def _extract_rank(raw: str) -> int | None:
    text = raw or ""
    rank_words = {
        "第一": 1,
        "第1": 1,
        "第二": 2,
        "第2": 2,
        "第三": 3,
        "第3": 3,
        "第四": 4,
        "第4": 4,
        "第五": 5,
        "第5": 5,
    }
    hits = []
    for key, value in rank_words.items():
        pos = text.find(key)
        if pos >= 0:
            hits.append((pos, value))
    if hits:
        return sorted(hits, key=lambda item: item[0])[0][1]
    digit_match = re.search(r"第\s*(\d{1,2})\s*(?:只|个|名)?", text)
    if digit_match:
        try:
            return int(digit_match.group(1))
        except Exception:
            return None
    match = _RANK_RE.search(raw or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def inject_entity_hints(frame: TurnFrame, memory_ctx: Dict, book: MarketBook) -> TurnFrame:
    refs = dict(frame.references or {})
    raw = (frame.raw_message or "").strip()
    session = memory_ctx["session"]
    active_entries = list(book.board)
    symbols = _SYMBOL_RE.findall(raw)
    if symbols and not refs.get("symbol"):
        refs["symbol"] = symbols[0]
    if len(symbols) >= 2 and not refs.get("compare_symbols"):
        refs["compare_symbols"] = symbols[:3]
    if refs.get("rank") is None:
        rank = _extract_rank(raw)
        if rank is not None:
            refs["rank"] = rank
    if "focus_symbol" not in refs and isinstance(session.focus_subject, dict):
        if session.focus_subject.get("type") == "symbol" and session.focus_subject.get("symbol"):
            refs["focus_symbol"] = session.focus_subject.get("symbol")
    if frame.request in {"pick_detail", "live_entry_check", "exit_decision"} and not refs.get("symbol") and refs.get("rank") is not None:
        entry = _entry_by_rank(active_entries, int(refs["rank"]))
        if entry:
            refs["symbol"] = entry.symbol
    frame.references = refs
    return frame


def resolve_subject_and_compare(
    *,
    frame,
    session,
    book: MarketBook,
    active_entries: List[BoardEntry],
) -> Tuple[BoardEntry | None, List[BoardEntry]]:
    refs = frame.references or {}
    subject_entry: BoardEntry | None = None
    if isinstance(refs.get("symbol"), str):
        subject_entry = _entry_by_symbol(active_entries, refs.get("symbol")) or _entry_by_symbol(book.board, refs.get("symbol"))
    if subject_entry is None and isinstance(refs.get("focus_symbol"), str):
        subject_entry = _entry_by_symbol(active_entries, refs.get("focus_symbol")) or _entry_by_symbol(book.board, refs.get("focus_symbol"))
    if subject_entry is None and refs.get("rank") is not None:
        try:
            subject_entry = _entry_by_rank(active_entries, int(refs.get("rank")))
        except Exception:
            subject_entry = None
    if subject_entry is None and isinstance(session.focus_subject, dict):
        if session.focus_subject.get("type") == "symbol":
            subject_entry = _entry_by_symbol(active_entries, session.focus_subject.get("symbol")) or _entry_by_symbol(book.board, session.focus_subject.get("symbol"))

    compare_entries: List[BoardEntry] = []
    compare_symbols: List[str] = []
    if isinstance(refs.get("compare_symbols"), list) and refs.get("compare_symbols"):
        compare_symbols = [str(symbol).strip() for symbol in refs["compare_symbols"] if str(symbol).strip()]
    elif isinstance(refs.get("symbols"), list) and refs.get("symbols"):
        compare_symbols = [str(symbol).strip() for symbol in refs["symbols"] if str(symbol).strip()]
    elif isinstance(session.compare_set, list) and session.compare_set:
        compare_symbols = [str(symbol).strip() for symbol in session.compare_set if str(symbol).strip()]
    if compare_symbols:
        wanted = set(compare_symbols)
        compare_entries = [entry for entry in (active_entries or book.board) if entry.symbol in wanted]
    if subject_entry and not compare_entries and frame.request == "compare":
        compare_entries = [subject_entry] + [entry for entry in active_entries if entry.symbol != subject_entry.symbol][:1]
    return subject_entry, compare_entries
