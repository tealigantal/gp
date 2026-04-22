from __future__ import annotations

from typing import List

from ..contracts.objects import MarketBook


def discover_symbols(book: MarketBook) -> List[str]:
    # current implementation keeps discovery conservative: only reserve symbols from daybook
    return [s for s in book.daybook.reserve_symbols[:10] if s not in book.watchset]
