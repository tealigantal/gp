from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .store import load_latest_candidate_target


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
    """Read the newest immutable preselection target; never read a recommendation."""
    target = load_latest_candidate_target()
    if target is None:
        return {"ok": False, "symbols": [], "reason": "candidate_target_unavailable"}
    targets = _symbols(target.symbols)
    return {
        "ok": bool(targets),
        "symbols": targets,
        "target_id": target.target_id,
        "decision_trade_day": target.decision_trade_day,
        "daybook_effective_day": target.daybook_effective_day,
        "observed_at": target.observed_at,
        "input_hash": target.input_hash,
        "activated_at": target.activated_at,
        "activation_observed_at": target.activation_observed_at,
        "activation_revision": target.activation_revision,
        "reason": None if targets else "candidate_target_empty",
    }
