from __future__ import annotations

from typing import Dict, Any

from ..contracts.objects import MarketBook, DayBook
from ..evidence.market_service import current_trading_day
from ..evidence.portfolio_service import load_portfolio_snapshot
from ..memory.service import list_hot_symbols
from ..runtime.utils import gen_id, now_iso
from .daybook import build_daybook
from .watchset import build_watchset
from .discovery import discover_symbols
from .pulse5m import apply_pulse
from .board import build_board
from .side_results import detect_side_results
from .repo import load_current_book, save_book


def _new_book(daybook: DayBook) -> MarketBook:
    trading_day = daybook.trading_day
    return MarketBook(
        trading_day=trading_day,
        book_version=gen_id(f'book_{trading_day}'),
        updated_at=now_iso(),
        regime=daybook.regime,
        daybook=daybook,
        board=[],
        watchset=[],
        symbol_states={},
        portfolio_snapshot=load_portfolio_snapshot(),
        last_closed_5m=None,
        side_results=[],
    )


def ensure_book(force_rebuild: bool = False) -> MarketBook:
    trading_day = current_trading_day()
    book = load_current_book()
    if force_rebuild or book is None or book.trading_day != trading_day:
        daybook = build_daybook(trading_day)
        book = _new_book(daybook)
    book.portfolio_snapshot = load_portfolio_snapshot()
    old_states = {k: v.execution_state for k, v in book.symbol_states.items()}
    hot_symbols = list_hot_symbols()
    holdings = [str(x.get('symbol') or '') for x in (book.portfolio_snapshot.get('positions') or []) if x.get('symbol')]
    book.watchset = build_watchset(book, hot_symbols, holdings)
    extra = discover_symbols(book)
    for sym in extra:
        if sym not in book.watchset:
            book.watchset.append(sym)
    book = apply_pulse(book, book.watchset)
    book.board = build_board(book.daybook, book.symbol_states)
    book.side_results = detect_side_results(old_states, book.board)
    book.updated_at = now_iso()
    save_book(book)
    return book


def load_current_book() -> MarketBook | None:
    from .repo import load_current_book as _load
    return _load()


def sync_book_once() -> Dict[str, Any]:
    book = ensure_book(force_rebuild=False)
    return {
        'trading_day': book.trading_day,
        'book_version': book.book_version,
        'watchset_size': len(book.watchset),
        'board_size': len(book.board),
        'last_closed_5m': book.last_closed_5m,
    }
