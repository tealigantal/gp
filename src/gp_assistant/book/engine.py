from __future__ import annotations

from typing import Dict, Any, Iterable, List

from ..contracts.objects import MarketBook, DayBook
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
from ..runtime.freshness_policy import RefreshPlan
from ..core.logging import logger


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
        daybook_effective_day=daybook.trading_day,
    )

def ensure_book(refresh_plan: RefreshPlan) -> MarketBook:
    """Ensure MarketBook aligns with the provided RefreshPlan.

    - L0: no refresh (return current book; still update metadata snapshot)
    - L1: pulse-only (restrict scope per plan)
    - L2: rebuild daybook (no pulse)
    - L3: rebuild daybook + pulse
    """
    book = load_current_book()
    need_rebuild = (
        book is None
        or not isinstance(book.daybook_effective_day, str)
        or book.daybook_effective_day != refresh_plan.target_daybook_effective_day
        or refresh_plan.level in {"L2", "L3"}
    )

    if need_rebuild:
        daybook = build_daybook(refresh_plan.target_daybook_effective_day)
        book = _new_book(daybook)

    # always refresh portfolio + watchset baseline
    book.portfolio_snapshot = load_portfolio_snapshot()
    old_states = {k: v.execution_state for k, v in book.symbol_states.items()}
    hot_symbols = list_hot_symbols()
    holdings = [str(x.get('symbol') or '') for x in (book.portfolio_snapshot.get('positions') or []) if x.get('symbol')]
    book.watchset = build_watchset(book, hot_symbols, holdings)
    extra = discover_symbols(book)
    for sym in extra:
        if sym not in book.watchset:
            book.watchset.append(sym)

    # apply pulse refresh by scope
    syms_used: List[str] = []
    if refresh_plan.level in {"L1", "L3"}:
        def _scope_symbols() -> List[str]:
            if refresh_plan.scope == 'subject_only' and refresh_plan.symbols_hint:
                return [s for s in refresh_plan.symbols_hint if s]
            if refresh_plan.scope == 'active_run':
                # minimal baseline: prefer board symbols, fall back to watchset
                if book.board:
                    return [e.symbol for e in book.board[: min(12, len(book.board))]]
                return book.watchset[:20]
            return list(book.watchset)

        syms = _scope_symbols()
        syms_used = syms
        book = apply_pulse(
            book,
            syms,
            target_trade_day=refresh_plan.target_pulse_trade_day,
            target_slot_at=refresh_plan.target_pulse_slot_at,
        )

    # rebuild board when daybook changed or after pulse update
    book.board = build_board(book.daybook, book.symbol_states)
    book.side_results = detect_side_results(old_states, book.board)

    # snapshot freshness metadata
    book.daybook_effective_day = refresh_plan.target_daybook_effective_day
    book.pulse_trade_day = refresh_plan.target_pulse_trade_day
    book.pulse_slot_at = refresh_plan.target_pulse_slot_at
    book.market_phase = refresh_plan.market_phase
    book.data_status = refresh_plan.data_status
    book.calendar_source = getattr(refresh_plan, 'calendar_source', book.calendar_source)

    book.updated_at = now_iso()
    save_book(book)
    try:
        logger.info(
            "[ensure_book] level=%s scope=%s syms=%d book=%s day=%s pulse_day=%s slot=%s phase=%s status=%s",
            refresh_plan.level,
            refresh_plan.scope,
            len(syms_used or []),
            book.book_version,
            book.daybook_effective_day,
            book.pulse_trade_day,
            book.pulse_slot_at,
            book.market_phase,
            book.data_status,
        )
    except Exception:
        pass
    return book


def load_current_book() -> MarketBook | None:
    from .repo import load_current_book as _load
    return _load()


def sync_book_once() -> Dict[str, Any]:
    # default: lightweight pulse-only on intraday, rebuild daybook when day changes via ensure_book planner upstream
    from ..runtime.freshness_policy import make_refresh_plan
    from ..memory.session_store import default_session
    plan = make_refresh_plan(session=default_session('default'), book=load_current_book(), user_message='')
    book = ensure_book(plan)
    return {
        'trading_day': book.trading_day,
        'book_version': book.book_version,
        'watchset_size': len(book.watchset),
        'board_size': len(book.board),
        'last_closed_5m': book.last_closed_5m,
    }
