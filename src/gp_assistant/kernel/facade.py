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
from ..validation.runner import build_validation_summary as _build_validation_summary
from ..gating.evaluator import apply_gating_to_artifact as _apply_gating
from ..execution.intent_builder import build_order_intents_from_gated_artifact as _build_intents
from ..execution.paper_engine import run_paper_execution as _run_paper
from ..portfolio.store import read_portfolio_state as _read_portfolio, read_recent_events as _read_events


# ---- Unified artifact access ----


def get_artifact_v2(run_id: Optional[str] = None, as_of: Optional[str] = None) -> Dict[str, Any]:
    return _read_artifact_v2(run_id=run_id, as_of=as_of)


def get_latest_artifact_v2() -> Dict[str, Any]:
    return _read_artifact_v2()


def compare_symbols(run_id: Optional[str], symbols: List[str]) -> Dict[str, Any]:
    # Use gated artifact to exclude blocked items from comparison
    art = get_gated_artifact_v2(run_id=run_id)
    syms = [s for s in (symbols or []) if s]
    subset = []
    for it in (art.get("items") or []):
        try:
            if it.get("symbol") in syms:
                subset.append(it)
        except Exception:
            continue
    # exclude blocked
    eligible = [it for it in subset if (it.get("gating_decision") or {}).get("decision") != "blocked"]
    def _rank_key(it: Dict[str, Any]):
        return (
            1 if bool(it.get("actionable") is True) else 0,
            float(it.get("execution_score") or 0.0),
            float(it.get("alpha_score") or 0.0),
            float(it.get("reliability_score") or 0.0),
        )
    ranked = sorted(eligible, key=_rank_key, reverse=True)
    winner = ranked[0]["symbol"] if ranked else None
    return {
        "ok": True,
        "artifact_version": "v2",
        "run_id": art.get("run_id"),
        "symbols": syms,
        "items": ranked,
        "ranking": [it.get("symbol") for it in ranked],
        "winner_symbol": winner,
        "summary": f"winner={winner}",
        "degraded": bool(art.get("degraded")) or ((art.get("run_gating") or {}).get("decision") == "degraded"),
        "errors": art.get("errors") or [],
        "fallback_used": bool(art.get("fallback_used", False)),
    }


def get_pick_detail(run_id: Optional[str], symbol: str) -> Dict[str, Any]:
    art = get_gated_artifact_v2(run_id=run_id)
    target = None
    for it in (art.get("items") or []):
        if str(it.get("symbol")) == str(symbol):
            target = it
            break
    if not target:
        return {"ok": False, "error": "PICK_NOT_FOUND", "run_id": art.get("run_id"), "symbol": symbol, "degraded": art.get("degraded")}
    return {
        "ok": True,
        "artifact_version": "v2",
        "run_id": art.get("run_id"),
        "as_of": art.get("as_of"),
        "degraded": art.get("degraded"),
        "fallback_used": bool(art.get("fallback_used", False)),
        "item": target,
    }


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


def get_validation_summary() -> Dict[str, Any]:
    """Unified read of consolidated validation summary.

    Preferred path: read store/validation/latest_summary.json. If missing,
    synthesize an in-memory summary from available pieces.
    """
    # Always rebuild to ensure the freshest view for gating (avoid stale cache)
    return _build_validation_summary()


def get_gated_artifact_v2(run_id: Optional[str] = None, as_of: Optional[str] = None) -> Dict[str, Any]:
    base = _read_artifact_v2(run_id=run_id, as_of=as_of)
    summary = get_validation_summary()
    gated = _apply_gating(base, summary=summary)
    gated.setdefault("artifact_version", base.get("artifact_version", "v2"))
    return gated


def build_order_intents(run_id: Optional[str] = None, as_of: Optional[str] = None) -> List[Dict[str, Any]]:
    art = get_gated_artifact_v2(run_id=run_id, as_of=as_of)
    return _build_intents(art)


def run_paper_execution(run_id: Optional[str] = None, as_of: Optional[str] = None) -> Dict[str, Any]:
    intents = build_order_intents(run_id=run_id, as_of=as_of)
    return _run_paper(intents)


def get_portfolio_state() -> Dict[str, Any]:
    return _read_portfolio()


def get_execution_events(limit: int = 100) -> List[Dict[str, Any]]:
    return _read_events(limit)
