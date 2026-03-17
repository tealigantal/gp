from __future__ import annotations

from typing import Any, Dict, List, Optional
import json

from ..core.paths import store_dir
from .contracts import build_v2_from_v1
from .validators import validate_pick_artifact_v2
from .calibration import apply_scores_to_v2_item


def _read_latest_v1() -> Dict[str, Any] | None:
    p = store_dir() / "recommend" / "latest.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_v1_by_run(run_id: str) -> Dict[str, Any] | None:
    base = store_dir() / "recommend"
    # try YYYYMMDD.json then YYYY-MM-DD.json
    cand = [base / f"{run_id}.json"]
    try:
        if len(run_id) == 8 and run_id.isdigit():
            cand.append(base / f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}.json")
    except Exception:
        pass
    for p in cand:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def _artifact_v2_from_store(run_id: Optional[str]) -> Dict[str, Any] | None:
    obj = _read_v1_by_run(run_id) if run_id else _read_latest_v1()
    if not isinstance(obj, dict):
        return None
    v2 = build_v2_from_v1(obj)
    out = {
        "run_id": v2.run_id,
        "as_of": v2.as_of,
        "snapshot_id": v2.snapshot_id,
        "market_regime": v2.market_regime,
        "degraded": v2.degraded,
        "tradeable": v2.tradeable,
        "reason": v2.reason,
        "risk_profile": v2.risk_profile,
        "universe_name": v2.universe_name,
        "symbols": v2.symbols,
        "themes": v2.themes,
        "items": [it.__dict__ for it in v2.items],
    }
    # enrich scores
    try:
        for it in out["items"]:
            apply_scores_to_v2_item(it, degraded=bool(out.get("degraded")))
    except Exception:
        pass
    return out


def compare_symbols(run_id: Optional[str], symbols: List[str]) -> Dict[str, Any]:
    syms = [s for s in (symbols or []) if s]
    art = _artifact_v2_from_store(run_id)
    if not isinstance(art, dict):
        return {"ok": False, "error": "ARTIFACT_NOT_FOUND"}

    ok, errs, fixed = validate_pick_artifact_v2(art)
    if not ok:
        fixed["degraded"] = True

    # choose subset
    subset: List[Dict[str, Any]] = []
    sym_set = set(syms)
    for it in (fixed.get("items") or []):
        try:
            if it.get("symbol") in sym_set:
                subset.append(it)
        except Exception:
            continue

    # sort by executability -> alpha -> reliability
    def _rank_key(it: Dict[str, Any]):
        return (
            1 if bool(it.get("actionable") is True) else 0,
            float(it.get("execution_score") or 0.0),
            float(it.get("alpha_score") or 0.0),
            float(it.get("reliability_score") or 0.0),
        )

    ranked = sorted(subset, key=_rank_key, reverse=True)
    winner = ranked[0]["symbol"] if ranked else None
    return {
        "ok": True,
        "run_id": fixed.get("run_id"),
        "symbols": syms,
        "items": ranked,
        "ranking": [it.get("symbol") for it in ranked],
        "winner_symbol": winner,
        "summary": f"winner={winner}",
        "degraded": bool(fixed.get("degraded")),
        "errors": errs if not ok else [],
    }


def pick_detail(run_id: Optional[str], symbol: str) -> Dict[str, Any]:
    art = _artifact_v2_from_store(run_id)
    if not isinstance(art, dict):
        return {"ok": False, "error": "ARTIFACT_NOT_FOUND"}
    ok, errs, fixed = validate_pick_artifact_v2(art)
    if not ok:
        fixed["degraded"] = True
    target = None
    for it in (fixed.get("items") or []):
        if str(it.get("symbol")) == str(symbol):
            target = it
            break
    if not target:
        return {"ok": False, "error": "PICK_NOT_FOUND", "run_id": fixed.get("run_id"), "symbol": symbol, "degraded": fixed.get("degraded")}
    return {
        "ok": True,
        "run_id": fixed.get("run_id"),
        "as_of": fixed.get("as_of"),
        "degraded": fixed.get("degraded"),
        "fallback_used": False,
        "item": target,
    }

