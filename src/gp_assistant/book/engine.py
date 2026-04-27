from __future__ import annotations

from typing import Any, Dict

from ..contracts.objects import DayBook, MarketBook
from ..runtime.market_clock import compute_market_state
from ..runtime.utils import now_iso
from .readonly import build_unavailable_market_book
from .repo import load_current_book as _load_current_book
from .repo import load_current_slot_artifact, load_daybook, load_latest_daybook, load_latest_saved_book


def _load_daybook_for_readonly(trading_day: str) -> DayBook:
    daybook = load_daybook(trading_day)
    if daybook is not None:
        return daybook
    saved = load_latest_saved_book(trading_day)
    if saved is not None:
        return saved.daybook
    latest_saved = load_latest_saved_book()
    if latest_saved is not None:
        return latest_saved.daybook
    latest = load_latest_daybook()
    if latest is not None:
        return latest
    return DayBook(
        trading_day=trading_day,
        generated_at=now_iso(),
        regime={},
        tradeable=False,
        reason="current_slot_unavailable",
    )


def _unavailable_book() -> MarketBook:
    ms = compute_market_state()
    daybook = _load_daybook_for_readonly(ms.target_daybook_effective_day)
    return build_unavailable_market_book(
        daybook=daybook,
        book_version=f"unavailable_{ms.target_daybook_effective_day}",
        market_phase=ms.market_phase,
        trade_day=ms.target_pulse_trade_day or ms.target_daybook_effective_day,
        slot_at=ms.target_pulse_slot_at,
        reason="current_slot_unavailable",
        data_status=ms.data_status,
    )


def book_is_fresh_for_plan(book: MarketBook | None, refresh_plan) -> bool:
    if book is None:
        return False
    return (
        book.daybook_effective_day == refresh_plan.target_daybook_effective_day
        and book.pulse_trade_day == refresh_plan.target_pulse_trade_day
        and book.pulse_slot_at == refresh_plan.target_pulse_slot_at
        and book.market_phase == refresh_plan.market_phase
    )


def ensure_book(refresh_plan) -> MarketBook:
    book = load_current_book()
    return book if book is not None else _unavailable_book()


def load_current_book() -> MarketBook | None:
    book = _load_current_book()
    if book is not None:
        return book
    return _unavailable_book()


def load_current_artifact_id() -> str | None:
    artifact = load_current_slot_artifact()
    return artifact.artifact_id if artifact is not None else None


def sync_book_once() -> Dict[str, Any]:
    from ..worker import reconcile_runtime_state

    return reconcile_runtime_state()
