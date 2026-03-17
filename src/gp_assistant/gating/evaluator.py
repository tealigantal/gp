from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from .contracts import (
    make_gating_decision,
    DECISION_ALLOW,
    DECISION_BLOCKED,
    DECISION_DEGRADED,
    attach_item_gating,
    attach_run_gating,
)
from . import policies as P


def _get_strategy_health(summary: Dict[str, Any], strategy: Optional[str]) -> Optional[str]:
    try:
        if not strategy:
            return None
        sec = (summary.get("parts") or {}).get("strategy_health") or {}
        st = sec.get(str(strategy)) or {}
        return st.get("status")
    except Exception:
        return None


def _has_walkforward(summary: Dict[str, Any], strategy: str) -> bool:
    try:
        sec = (summary.get("parts") or {}).get("walkforward") or {}
        obj = sec.get(str(strategy))
        if obj is None:
            return False
        # if an object exists but explicitly marks available False
        return bool(obj.get("available", True))
    except Exception:
        return False


def evaluate_item_gating(item: Dict[str, Any], *, summary: Dict[str, Any], fallback_used: bool) -> Dict[str, Any]:
    d = make_gating_decision(level="item")
    snap: Dict[str, Any] = {}
    # inputs capture
    snap["final_score"] = item.get("final_score")
    snap["reliability_score"] = item.get("reliability_score")
    snap["invalidated_now"] = item.get("invalidated_now")
    snap["actionable"] = item.get("actionable")
    snap["strategy"] = item.get("strategy")
    d["inputs_snapshot"] = snap
    d["fallback_used"] = bool(fallback_used)
    # invalidation
    if bool(item.get("invalidated_now") is True):
        d["decision"] = DECISION_BLOCKED
        d["reasons"].append("invalidated_now")
        d["triggered_rules"].append("item.invalidated_now->blocked")
        return d
    # strategy health
    status = _get_strategy_health(summary, item.get("strategy"))
    if status in P.HEALTH_BLOCK:
        d["decision"] = DECISION_BLOCKED
        d["reasons"].append(f"strategy_health={status}")
        d["triggered_rules"].append("item.strategy_health=killed->blocked")
        return d
    if status in P.HEALTH_DEGRADE:
        d["decision"] = DECISION_DEGRADED
        d["reasons"].append(f"strategy_health={status}")
        d["triggered_rules"].append("item.strategy_health=degraded->degraded")
    # final score thresholds
    try:
        fs = float(item.get("final_score") or 0.0)
        if fs < P.FINAL_SCORE_BLOCK:
            d["decision"] = DECISION_BLOCKED
            d["reasons"].append(f"final_score<{P.FINAL_SCORE_BLOCK}")
            d["triggered_rules"].append("item.final_score->blocked")
            return d
        elif fs < P.FINAL_SCORE_DEGRADE and d["decision"] != DECISION_DEGRADED:
            d["decision"] = DECISION_DEGRADED
            d["reasons"].append(f"final_score<{P.FINAL_SCORE_DEGRADE}")
            d["triggered_rules"].append("item.final_score->degraded")
    except Exception:
        pass
    # reliability thresholds
    try:
        rs = float(item.get("reliability_score") or 0.0)
        if rs < P.RELIABILITY_BLOCK:
            d["decision"] = DECISION_BLOCKED
            d["reasons"].append(f"reliability<{P.RELIABILITY_BLOCK}")
            d["triggered_rules"].append("item.reliability->blocked")
            return d
        elif rs < P.RELIABILITY_DEGRADE and d["decision"] != DECISION_DEGRADED:
            d["decision"] = DECISION_DEGRADED
            d["reasons"].append(f"reliability<{P.RELIABILITY_DEGRADE}")
            d["triggered_rules"].append("item.reliability->degraded")
    except Exception:
        pass
    # fallback
    if fallback_used and d["decision"] == DECISION_ALLOW:
        d["decision"] = DECISION_DEGRADED
        d["reasons"].append("fallback_used")
        d["triggered_rules"].append("item.fallback_used->degraded")
    return d


def evaluate_run_gating(artifact: Dict[str, Any], *, summary: Dict[str, Any]) -> Dict[str, Any]:
    d = make_gating_decision(level="run")
    # strategies present in artifact
    strategies: Set[str] = set()
    for it in (artifact.get("items") or []):
        s = it.get("strategy")
        if isinstance(s, str) and s:
            strategies.add(s)
    # walkforward available ratio
    if strategies:
        wf_missing = 0
        for s in strategies:
            if not _has_walkforward(summary, s):
                wf_missing += 1
        ratio = wf_missing / max(1, len(strategies))
        if ratio > P.WALKFORWARD_MISSING_DEGRADE_RATIO:
            d["decision"] = DECISION_DEGRADED
            d["reasons"].append("walkforward_missing_majority")
            d["triggered_rules"].append("run.walkforward->degraded")
    # live_shadow advisory
    try:
        ls = (summary.get("parts") or {}).get("live_shadow") or {}
        if not bool(ls.get("available", False)):
            d["warnings"].append("live_shadow_unavailable")
    except Exception:
        d["warnings"].append("live_shadow_unavailable")
    return d


def apply_gating_to_artifact(artifact: Dict[str, Any], *, summary: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(artifact)
    items = [dict(it) for it in (artifact.get("items") or [])]
    fallback = bool(artifact.get("fallback_used", False))
    for it in items:
        dec = evaluate_item_gating(it, summary=summary, fallback_used=fallback)
        attach_item_gating(it, dec)
    out["items"] = items
    run_dec = evaluate_run_gating(out, summary=summary)
    attach_run_gating(out, run_dec)
    return out

