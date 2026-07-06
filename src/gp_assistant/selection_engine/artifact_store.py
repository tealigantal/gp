from __future__ import annotations

"""
Unified V2 artifact store/helper (Phase 2.6).

Centralizes:
- read V2
- write V2
- fallback v1 -> v2 conversion
- validator check and score calculation
- artifact_version / fallback_used / degraded flags

Reading priority:
1) persisted V2
2) fallback from v1 -> v2
3) validate and mark degraded/errors
"""

from typing import Any, Dict, List, Optional
import json
import uuid

from ..core.paths import store_dir
from .contracts import build_v2_from_v1
from .validators import validate_pick_artifact_v2
from .calibration import apply_scores_to_v2_item, compute_no_trade_gate
from ..validation.event_stats import load_event_stats
from ..validation.walkforward_stats import load_walkforward
from ..validation.paper_trade import load_paperfolio
from ..validation.strategy_health import load_strategy_health


def _read_v2_from_store(run_id: Optional[str], as_of: Optional[str]) -> Dict[str, Any] | None:
    base = store_dir() / "recommend"
    cand = []
    if run_id:
        cand.append(base / f"{run_id}_v2.json")
        try:
            if len(str(run_id)) == 8 and str(run_id).isdigit():
                cand.append(base / f"{str(run_id)[:4]}-{str(run_id)[4:6]}-{str(run_id)[6:8]}_v2.json")
        except Exception:
            pass
    if as_of and not run_id:
        cand.append(base / f"{as_of}_v2.json")
        try:
            if len(str(as_of)) == 8 and str(as_of).isdigit():
                cand.append(base / f"{str(as_of)[:4]}-{str(as_of)[4:6]}-{str(as_of)[6:8]}_v2.json")
        except Exception:
            pass
    if not run_id and not as_of:
        cand.append(base / "latest_v2.json")
    for p in cand:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def _read_v1_from_store(run_id: Optional[str], as_of: Optional[str]) -> Dict[str, Any] | None:
    base = store_dir() / "recommend"
    cand = []
    if run_id:
        cand.append(base / f"{run_id}.json")
        try:
            if len(str(run_id)) == 8 and str(run_id).isdigit():
                cand.append(base / f"{str(run_id)[:4]}-{str(run_id)[4:6]}-{str(run_id)[6:8]}.json")
        except Exception:
            pass
    if as_of and not run_id:
        cand.append(base / f"{as_of}.json")
        try:
            if len(str(as_of)) == 8 and str(as_of).isdigit():
                cand.append(base / f"{str(as_of)[:4]}-{str(as_of)[4:6]}-{str(as_of)[6:8]}.json")
        except Exception:
            pass
    if not run_id and not as_of:
        cand.append(base / "latest.json")
    for p in cand:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def _enrich_scores_and_gate(obj: Dict[str, Any]) -> None:
    degraded = bool(obj.get("degraded"))
    try:
        for it in (obj.get("items") or []):
            if isinstance(it, dict):
                apply_scores_to_v2_item(it, degraded=degraded)
                # Attach evidence blocks (best-effort)
                strat = str(it.get("strategy") or "")
                ev = it.get("evidence") or {}
                ev.setdefault("available", True)
                try:
                    if strat:
                        ev["event_stats"] = load_event_stats(strat)
                        ev["walk_forward"] = load_walkforward(strat)
                        sh = load_strategy_health(strat)
                        ev["strategy_health"] = sh
                        # reliability penalty on degraded/killed strategies (deterministic)
                        if sh.get("status") in {"degraded", "killed"}:
                            try:
                                rel = float(it.get("reliability_score") or 0.6)
                                penalty = 0.2 if sh["status"] == "degraded" else 0.4
                                new_rel = max(0.2, rel - penalty)
                                it["reliability_score"] = new_rel
                                # deterministically recompute final using existing alpha/execution and new reliability
                                try:
                                    alpha = float(it.get("alpha_score") or 0.0)
                                except Exception:
                                    alpha = 0.0
                                try:
                                    exec_score = float(it.get("execution_score") or 0.0)
                                except Exception:
                                    exec_score = 0.0
                                final = 0.45 * exec_score + 0.35 * alpha + 0.20 * new_rel
                                if final < 0.0:
                                    final = 0.0
                                if final > 1.0:
                                    final = 1.0
                                it["final_score"] = final
                                it["confidence"] = new_rel
                            except Exception:
                                pass
                except Exception:
                    pass
                try:
                    # Attach paper trade summary at symbol level when available
                    pf = load_paperfolio()
                    sym = str(it.get("symbol"))
                    match = None
                    for pk in (pf.get("picks") or []):
                        if str(pk.get("symbol")) == sym:
                            match = pk; break
                    if match:
                        ev["paper_trade"] = match
                except Exception:
                    pass
                it["evidence"] = ev
    except Exception:
        pass
    gate = compute_no_trade_gate(obj)
    if gate.get("tradeable") is False:
        obj["tradeable"] = False
        obj["reason"] = gate.get("reason")


def build_v2_dict_from_v1(payload: Dict[str, Any], *, risk_profile: Optional[str] = None, universe: Optional[str] = None) -> Dict[str, Any]:
    v2 = build_v2_from_v1(payload, risk_profile=risk_profile, universe=universe)
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
        "market_context": v2.market_context,
        "items": [it.__dict__ for it in v2.items],
        "artifact_version": "v2",
        "fallback_used": False,
    }
    # Ensure a unique run_id not tied to as_of
    try:
        rid = str(out.get("run_id") or "")
        # treat pure date-like IDs as insufficient; replace with uuid4
        if (not rid) or rid.isdigit() or (len(rid) == 10 and rid[4] == '-' and rid[7] == '-'):
            out["run_id"] = uuid.uuid4().hex
    except Exception:
        out["run_id"] = uuid.uuid4().hex

    _enrich_scores_and_gate(out)
    ok, errs, fixed = validate_pick_artifact_v2(out)
    if not ok:
        fixed["degraded"] = True
        fixed.setdefault("reason", "artifact_validation_failed")
        fixed.setdefault("errors", errs)
    fixed.setdefault("artifact_version", "v2")
    fixed.setdefault("fallback_used", False)
    return fixed


def read_artifact_v2(run_id: Optional[str] = None, as_of: Optional[str] = None) -> Dict[str, Any]:
    if not run_id and not as_of:
        base = store_dir() / "recommend"
        latest_v2 = base / "latest_v2.json"
        latest_v1 = base / "latest.json"
        try:
            if latest_v1.exists() and (not latest_v2.exists() or latest_v1.stat().st_mtime > latest_v2.stat().st_mtime):
                v1_latest = _read_v1_from_store(None, None)
                if isinstance(v1_latest, dict):
                    out = build_v2_dict_from_v1(v1_latest)
                    out["fallback_used"] = True
                    return out
        except Exception:
            pass
    # 1) prefer persisted v2
    v2p = _read_v2_from_store(run_id, as_of)
    if isinstance(v2p, dict):
        ok, errs, fixed = validate_pick_artifact_v2(v2p)
        if not ok:
            fixed["degraded"] = True
            fixed.setdefault("reason", "artifact_validation_failed")
            fixed.setdefault("errors", errs)
        fixed.setdefault("artifact_version", "v2")
        fixed.setdefault("fallback_used", False)
        return fixed
    # 2) fallback: v1 -> v2 conversion
    v1 = _read_v1_from_store(run_id, as_of)
    if not isinstance(v1, dict):
        raise FileNotFoundError("ARTIFACT_NOT_FOUND")
    out = build_v2_dict_from_v1(v1)
    out["fallback_used"] = True
    return out


def persist_artifact_v2(run_id: str, v2_obj: Dict[str, Any]) -> None:
    base = store_dir() / "recommend"
    base.mkdir(parents=True, exist_ok=True)
    # enrich scores/gating if necessary then validate and write
    try:
        _enrich_scores_and_gate(v2_obj)
    except Exception:
        pass
    ok, errs, fixed = validate_pick_artifact_v2(v2_obj)
    if not ok:
        fixed["degraded"] = True
        fixed.setdefault("reason", "artifact_validation_failed")
        fixed.setdefault("errors", errs)
    fixed.setdefault("artifact_version", "v2")
    fixed.setdefault("fallback_used", False)
    (base / f"{run_id}_v2.json").write_text(json.dumps(fixed, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        (base / "latest_v2.json").write_text(json.dumps(fixed, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def compare_subset(run_id: Optional[str], symbols: List[str]) -> Dict[str, Any]:
    art = read_artifact_v2(run_id=run_id)
    syms = [s for s in (symbols or []) if s]
    subset: List[Dict[str, Any]] = []
    sym_set = set(syms)
    for it in (art.get("items") or []):
        try:
            if it.get("symbol") in sym_set:
                subset.append(it)
        except Exception:
            continue

    # rank by actionable -> execution -> alpha -> reliability
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
        "artifact_version": "v2",
        "run_id": art.get("run_id"),
        "symbols": syms,
        "items": ranked,
        "ranking": [it.get("symbol") for it in ranked],
        "winner_symbol": winner,
        "summary": f"winner={winner}",
        "degraded": bool(art.get("degraded")),
        "errors": art.get("errors") or [],
        "fallback_used": bool(art.get("fallback_used", False)),
    }


def pick_detail(run_id: Optional[str], symbol: str) -> Dict[str, Any]:
    art = read_artifact_v2(run_id=run_id)
    target = None
    for it in (art.get("items") or []):
        if str(it.get("symbol")) == str(symbol):
            target = it
            break
    if not target:
        return {
            "ok": False,
            "artifact_version": "v2",
            "error": "PICK_NOT_FOUND",
            "run_id": art.get("run_id"),
            "symbol": symbol,
            "degraded": art.get("degraded"),
            "fallback_used": bool(art.get("fallback_used", False)),
        }
    return {
        "ok": True,
        "artifact_version": "v2",
        "run_id": art.get("run_id"),
        "as_of": art.get("as_of"),
        "degraded": art.get("degraded"),
        "fallback_used": bool(art.get("fallback_used", False)),
        "item": target,
    }
