from __future__ import annotations

from typing import Any, Dict, Iterable, List

from ..agent_store import AgentStore


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
    """Read one immutable published snapshot; no book/run or portfolio fallback."""
    snapshot = AgentStore().current_snapshot()
    if snapshot is None:
        return {"ok": False, "symbols": [], "reason": "current_snapshot_unavailable"}
    book = AgentStore().book_for_snapshot(snapshot)
    tracked = getattr(book, "tracked_universe", None)
    reco = list(getattr(tracked, "reco", []) or [])[:10]
    reserve = list(getattr(tracked, "reserve", []) or [])[:2]
    if not reco:
        reco = [getattr(entry, "symbol", None) for entry in list(getattr(book, "board", []) or [])[:10]]
    targets = _symbols([*reco, *reserve])
    return {
        "ok": bool(targets), "symbols": targets, "reco": _symbols(reco), "reserve": _symbols(reserve),
        "book_version": getattr(book, "book_version", None), "artifact_id": snapshot.snapshot_id,
        "trade_day": getattr(book, "trading_day", None), "reason": None if targets else "target_set_empty",
    }
