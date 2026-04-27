from __future__ import annotations

from typing import List

from ..contracts.objects import MarketBook


def build_watchset(book: MarketBook, hot_symbols: List[str], holdings: List[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    tracked_reco = [p.symbol for p in book.daybook.picks[:10]]
    reserve = [p.symbol for p in book.daybook.reserve_picks[:2]] or list(book.daybook.reserve_symbols[:2])
    for sym in tracked_reco + reserve + holdings:
        s = str(sym).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out
