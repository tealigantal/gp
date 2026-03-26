from __future__ import annotations

from typing import List

from ..contracts.objects import MarketBook


def build_watchset(book: MarketBook, hot_symbols: List[str], holdings: List[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for sym in holdings + hot_symbols + [p.symbol for p in book.daybook.picks] + list(book.daybook.reserve_symbols[:15]):
        s = str(sym).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out[:40]
