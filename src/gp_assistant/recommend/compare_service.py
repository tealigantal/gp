from __future__ import annotations

from typing import Any, Dict, List, Optional

from .artifact_store import read_artifact_v2, compare_subset as _compare_subset, pick_detail as _pick_detail


def _artifact_v2_from_store(run_id: Optional[str]) -> Dict[str, Any] | None:
    try:
        return read_artifact_v2(run_id=run_id)
    except Exception:
        return None


def compare_symbols(run_id: Optional[str], symbols: List[str]) -> Dict[str, Any]:
    return _compare_subset(run_id, symbols)


def pick_detail(run_id: Optional[str], symbol: str) -> Dict[str, Any]:
    return _pick_detail(run_id, symbol)
