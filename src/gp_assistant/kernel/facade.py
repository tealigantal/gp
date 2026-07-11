from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from ..execution.intent_builder import build_order_intents_from_gated_artifact
from ..execution.paper_engine import run_paper_execution as _run_paper_execution
from ..portfolio.store import read_portfolio_state, read_recent_events
from ..selection_engine.artifact_store import read_artifact_v2
from ..book.engine import load_current_book
from ..runtime.current_v2 import current_book_to_v2
from ..validation.event_stats import load_event_stats
from ..validation.runner import build_validation_summary
from ..validation.strategy_health import load_strategy_health
from ..validation.walkforward_stats import load_walkforward


def get_artifact_v2(run_id: Optional[str] = None, as_of: Optional[str] = None) -> Dict[str, Any]:
    if not run_id and not as_of:
        return current_book_to_v2(load_current_book())
    return read_artifact_v2(run_id=run_id, as_of=as_of)


def _strategy_id(item: Dict[str, Any]) -> str:
    return str(item.get("strategy") or item.get("strategy_id") or "").strip()


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _item_gating_decision(item: Dict[str, Any]) -> Dict[str, Any]:
    reasons: List[str] = []
    warnings: List[str] = []
    decision = "allow"

    if bool(item.get("invalidated_now") is True):
        decision = "blocked"
        reasons.append("invalidated_now")

    strategy = _strategy_id(item)
    health = load_strategy_health(strategy) if strategy else {"available": False, "status": "unknown"}
    health_status = str(health.get("status") or "unknown")
    if health_status == "killed":
        decision = "blocked"
        reasons.append("strategy_health:killed")
    elif health_status == "degraded" and decision != "blocked":
        decision = "degraded"
        reasons.append("strategy_health:degraded")
    elif health_status == "warning":
        warnings.append("strategy_health:warning")

    return {
        "decision": decision,
        "reasons": reasons,
        "warnings": warnings,
        "strategy": strategy or None,
        "strategy_health": {
            "status": health_status,
            "available": bool(health.get("available", False)),
            "reason_codes": list(health.get("reason_codes") or []),
        },
    }


def get_live_shadow_latest_summary() -> Dict[str, Any]:
    return {"available": False, "dates": []}


def _run_gating_decision(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    reasons: List[str] = []
    warnings: List[str] = []
    dict_items = [item for item in items if isinstance(item, dict)]
    strategies = sorted({_strategy_id(item) for item in dict_items if _strategy_id(item)})

    if dict_items and all((item.get("gating_decision") or {}).get("decision") == "blocked" for item in dict_items):
        decision = "blocked"
        reasons.append("all_items_blocked")
    else:
        decision = "allow"

    missing_walkforward: List[str] = []
    for strategy in strategies:
        wf = load_walkforward(strategy)
        if not bool(wf.get("available", False)):
            missing_walkforward.append(strategy)
    if missing_walkforward and decision != "blocked":
        decision = "degraded"
        reasons.extend(f"walkforward_missing:{strategy}" for strategy in missing_walkforward)

    live_shadow = get_live_shadow_latest_summary()
    if not bool(live_shadow.get("available", False)):
        warnings.append("live_shadow_unavailable")

    return {
        "decision": decision,
        "reasons": reasons,
        "warnings": warnings,
        "checked_strategies": strategies,
        "live_shadow": live_shadow,
    }


def get_gated_artifact_v2(run_id: Optional[str] = None, as_of: Optional[str] = None) -> Dict[str, Any]:
    art = deepcopy(get_artifact_v2(run_id=run_id, as_of=as_of))
    items = art.get("items") if isinstance(art.get("items"), list) else []
    for item in items:
        if isinstance(item, dict):
            item["gating_decision"] = _item_gating_decision(item)
    art["items"] = items
    art["run_gating"] = _run_gating_decision(items)
    return art


def _rank_key(item: Dict[str, Any]) -> tuple[float, float, float, float, float]:
    return (
        1.0 if bool(item.get("actionable") is True) else 0.0,
        _safe_float(item.get("final_score")),
        _safe_float(item.get("execution_score")),
        _safe_float(item.get("alpha_score")),
        _safe_float(item.get("reliability_score")),
    )


def compare_symbols(run_id: Optional[str], symbols: List[str]) -> Dict[str, Any]:
    art = get_gated_artifact_v2(run_id=run_id)
    requested = [str(symbol).strip() for symbol in (symbols or []) if str(symbol).strip()]
    wanted = set(requested)
    subset = [
        item
        for item in (art.get("items") or [])
        if isinstance(item, dict) and str(item.get("symbol") or "") in wanted
    ]
    allowed = [
        item
        for item in subset
        if (item.get("gating_decision") or {}).get("decision") != "blocked"
    ]
    ranked_allowed = sorted(allowed, key=_rank_key, reverse=True)
    ranked_blocked = sorted([item for item in subset if item not in allowed], key=_rank_key, reverse=True)
    ranked = ranked_allowed + ranked_blocked
    winner = ranked_allowed[0].get("symbol") if ranked_allowed else None
    return {
        "ok": True,
        "artifact_version": "v2",
        "run_id": art.get("run_id"),
        "symbols": requested,
        "items": ranked,
        "ranking": [item.get("symbol") for item in ranked],
        "winner_symbol": winner,
        "summary": f"winner={winner}",
        "degraded": bool(art.get("degraded")),
        "errors": art.get("errors") or [],
        "fallback_used": bool(art.get("fallback_used", False)),
    }


def get_pick_detail(run_id: Optional[str], symbol: str) -> Dict[str, Any]:
    art = get_gated_artifact_v2(run_id=run_id)
    target = None
    for item in art.get("items") or []:
        if isinstance(item, dict) and str(item.get("symbol")) == str(symbol):
            target = item
            break
    if target is None:
        return {
            "ok": False,
            "artifact_version": "v2",
            "error": "PICK_NOT_FOUND",
            "run_id": art.get("run_id"),
            "symbol": symbol,
            "degraded": bool(art.get("degraded")),
            "fallback_used": bool(art.get("fallback_used", False)),
        }
    return {
        "ok": True,
        "artifact_version": "v2",
        "run_id": art.get("run_id"),
        "as_of": art.get("as_of"),
        "degraded": bool(art.get("degraded")),
        "fallback_used": bool(art.get("fallback_used", False)),
        "item": target,
    }


def get_strategy_validation(strategy: str) -> Dict[str, Any]:
    return {
        "strategy": strategy,
        "event_stats": load_event_stats(strategy),
        "walk_forward": load_walkforward(strategy),
        "strategy_health": load_strategy_health(strategy),
    }


def get_validation_summary() -> Dict[str, Any]:
    return build_validation_summary()


def get_portfolio_state() -> Dict[str, Any]:
    state = read_portfolio_state()
    state["recent_events"] = read_recent_events(limit=100)
    return state


def build_order_intents(run_id: Optional[str] = None, as_of: Optional[str] = None) -> List[Dict[str, Any]]:
    art = get_gated_artifact_v2(run_id=run_id, as_of=as_of)
    return build_order_intents_from_gated_artifact(art)


def run_paper_execution(run_id: Optional[str] = None, as_of: Optional[str] = None) -> Dict[str, Any]:
    return _run_paper_execution(build_order_intents(run_id=run_id, as_of=as_of))


def get_workbench_snapshot(run_id: Optional[str] = None, as_of: Optional[str] = None) -> Dict[str, Any]:
    recommend = get_gated_artifact_v2(run_id=run_id, as_of=as_of)
    return {
        "recommend": recommend,
        "portfolio": get_portfolio_state(),
        "validation_summary": get_validation_summary(),
        "execution_events": read_recent_events(limit=100),
        "intents_preview": build_order_intents_from_gated_artifact(recommend),
    }
