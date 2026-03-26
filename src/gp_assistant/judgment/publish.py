from __future__ import annotations

from ..contracts.objects import AdviceRun, MarketBook
from ..runtime.utils import gen_id, now_iso
from ..book.repo import save_run


def publish_run(session_id: str, book: MarketBook, topk: int = 3) -> AdviceRun:
    run = AdviceRun(
        run_id=gen_id('run'),
        session_id=session_id,
        book_version=book.book_version,
        created_at=now_iso(),
        trading_day=book.trading_day,
        regime=book.regime,
        tradeable=book.daybook.tradeable,
        reason=book.daybook.reason,
        picks=book.board[:topk],
        evidence_refs=[book.book_version],
    )
    save_run(run)
    return run
