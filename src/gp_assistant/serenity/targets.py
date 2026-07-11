from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List

from ..book.repo import load_current_book, load_current_pointer
from ..evidence.portfolio_service import load_portfolio_snapshot


def _symbols(values: Iterable[Any]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for value in values:
        symbol = str(value or "").strip()
        if symbol and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return out


def load_stable_targets(*, retries: int = 3, retry_delay_sec: float = 0.05) -> Dict[str, Any]:
    last_reason = "current_book_unavailable"
    for _ in range(max(1, retries)):
        pointer_a = load_current_pointer()
        book = load_current_book()
        pointer_b = load_current_pointer()
        if pointer_a is None or pointer_b is None or book is None:
            last_reason = "current_pointer_or_book_unavailable"
            time.sleep(retry_delay_sec)
            continue
        stable = (
            pointer_a.artifact_id == pointer_b.artifact_id
            and pointer_a.trade_day == pointer_b.trade_day
            and str(getattr(book, "artifact_id", "") or "") == str(pointer_a.artifact_id or "")
        )
        if not stable:
            last_reason = "current_pointer_changed_during_read"
            time.sleep(retry_delay_sec)
            continue
        tracked = getattr(book, "tracked_universe", None)
        reco = list(getattr(tracked, "reco", []) or [])[:10]
        reserve = list(getattr(tracked, "reserve", []) or [])[:2]
        if not reco:
            reco = [getattr(entry, "symbol", None) for entry in list(getattr(book, "board", []) or [])[:10]]
        portfolio = load_portfolio_snapshot()
        holdings = [row.get("symbol") for row in list(portfolio.get("positions") or [])]
        targets = _symbols([*reco, *reserve, *holdings])
        return {
            "ok": bool(targets),
            "symbols": targets,
            "reco": _symbols(reco),
            "reserve": _symbols(reserve),
            "portfolio": _symbols(holdings),
            "book_version": getattr(book, "book_version", None),
            "artifact_id": getattr(book, "artifact_id", None),
            "trade_day": getattr(book, "trading_day", None),
            "reason": None if targets else "target_set_empty",
        }
    return {"ok": False, "symbols": [], "reason": last_reason}
