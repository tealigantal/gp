from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from ..selection_engine.artifact_store import pick_detail
from . import session_store


@dataclass
class _Registry:
    def get_pick_detail(self, session_id: str, symbol: str) -> Dict[str, object]:
        state = session_store.get_state(session_id)
        run_id = state.get("referenced_run_id") or state.get("active_run_id")
        out = pick_detail(run_id=run_id, symbol=symbol)
        item = out.get("item") or {}
        return {"symbol": item.get("symbol") or symbol, **item}


def build_registry() -> _Registry:
    return _Registry()
