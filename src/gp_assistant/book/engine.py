from __future__ import annotations

from typing import Any, Dict

from ..contracts.objects import DayBook, MarketBook
from ..agent_store import AgentStore


def book_is_fresh_for_plan(book: MarketBook | None, refresh_plan) -> bool:
    if book is None:
        return False
    return (
        book.daybook_effective_day == refresh_plan.target_daybook_effective_day
        and book.market_phase == refresh_plan.market_phase
    )


def ensure_book(refresh_plan) -> MarketBook:
    book = load_current_book()
    if book is None:
        raise RuntimeError("current_snapshot_unavailable")
    return book


def load_current_book() -> MarketBook | None:
    return AgentStore().current_book()


def load_current_artifact_id() -> str | None:
    snapshot = AgentStore().current_snapshot()
    return snapshot.snapshot_id if snapshot else None


def sync_book_once() -> Dict[str, Any]:
    from ..worker import reconcile_runtime_state

    return reconcile_runtime_state()
