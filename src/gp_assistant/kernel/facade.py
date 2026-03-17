from __future__ import annotations

from typing import Any, Dict, List, Optional

# Artifact + validation sources
from ..recommend.artifact_store import read_artifact_v2 as _read_artifact_v2
from ..recommend.artifact_store import compare_subset as _compare_subset
from ..recommend.artifact_store import pick_detail as _pick_detail
from ..validation.event_stats import load_event_stats as _load_event_stats
from ..validation.walkforward_stats import load_walkforward as _load_walkforward
from ..validation.strategy_health import load_strategy_health as _load_strategy_health
from ..validation.paper_trade import load_paperfolio as _load_paperfolio
from .live_shadow import latest_live_shadow_summary as _latest_live_shadow_summary


# ---- Unified artifact access ----


def get_artifact_v2(run_id: Optional[str] = None, as_of: Optional[str] = None) -> Dict[str, Any]:
    return _read_artifact_v2(run_id=run_id, as_of=as_of)


def get_latest_artifact_v2() -> Dict[str, Any]:
    return _read_artifact_v2()


def compare_symbols(run_id: Optional[str], symbols: List[str]) -> Dict[str, Any]:
    return _compare_subset(run_id, symbols)


def get_pick_detail(run_id: Optional[str], symbol: str) -> Dict[str, Any]:
    return _pick_detail(run_id, symbol)


# ---- Validation & health ----


def get_strategy_validation(strategy: str) -> Dict[str, Any]:
    return {
        "strategy": strategy,
        "event_stats": _load_event_stats(strategy),
        "walk_forward": _load_walkforward(strategy),
        "strategy_health": _load_strategy_health(strategy),
    }


def get_paperfolio() -> Dict[str, Any]:
    return _load_paperfolio()


# ---- Live shadow ----


def get_live_shadow_latest_summary() -> Dict[str, Any]:
    return _latest_live_shadow_summary()

