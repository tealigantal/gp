from __future__ import annotations

from ..book.repo import load_current_book


def list_side_results() -> list[dict]:
    book = load_current_book()
    if not book:
        return []
    return [s.model_dump() for s in book.side_results]
