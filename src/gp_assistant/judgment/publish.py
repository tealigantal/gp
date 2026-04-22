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
        daybook_effective_day=book.daybook_effective_day,
        pulse_trade_day=book.pulse_trade_day,
        pulse_slot_at=book.pulse_slot_at,
        market_phase=book.market_phase,
        data_status=book.data_status,
    )
    save_run(run)
    return run
