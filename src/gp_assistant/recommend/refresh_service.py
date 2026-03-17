from __future__ import annotations

"""
Canonical refresh service (Phase 2).

Recomputes a V2 artifact for a given symbol set using the default agent
pipeline and converts to PickArtifactV2. This is the single source that
chat/service layers should call; chat may add a thin wrapper for
backward-compatible response shapes.
"""

from typing import Any, Dict, List, Optional

from .runner import run as _run
from .contracts import build_v2_from_v1
from .validators import validate_pick_artifact_v2
from .calibration import apply_scores_to_v2_item, compute_no_trade_gate


def refresh_symbols_v2(symbols: List[str], *, as_of: Optional[str] = None, risk_profile: Optional[str] = None) -> Dict[str, Any]:
    syms = [str(s).strip() for s in (symbols or []) if str(s).strip()]
    if not syms:
        return {"ok": False, "error": "NO_SYMBOLS"}

    res = _run(universe="symbols", symbols=syms, date=as_of, topk=len(syms))
    art = build_v2_from_v1(res, risk_profile=risk_profile, universe="symbols")

    # enrich scores deterministically
    try:
        degraded = bool(getattr(art, "degraded", False))
    except Exception:
        degraded = False
    try:
        for it in art.items:
            apply_scores_to_v2_item(it.__dict__, degraded=degraded)
    except Exception:
        # best-effort on error
        pass

    # top-level gating (no-trade day)
    top = {
        "run_id": art.run_id,
        "as_of": art.as_of,
        "snapshot_id": art.snapshot_id,
        "market_regime": art.market_regime,
        "degraded": art.degraded,
        "tradeable": art.tradeable,
        "reason": art.reason,
        "risk_profile": risk_profile,
        "universe_name": art.universe_name,
        "symbols": art.symbols,
        "themes": art.themes,
        "items": [it.__dict__ for it in art.items],
    }

    # If engine marked tradeable=True but gating says otherwise, prefer gate
    gate = compute_no_trade_gate(top)
    if gate.get("tradeable") is False:
        top["tradeable"] = False
        top["reason"] = gate.get("reason")

    ok, errs, fixed = validate_pick_artifact_v2(top)
    if not ok:
        # fail closed with degraded flag
        fixed["degraded"] = True
        fixed.setdefault("reason", "artifact_validation_failed")
        fixed.setdefault("errors", errs)
    fixed["ok"] = ok
    # Provide a compatibility picks array for chat card (from original v1 res)
    try:
        fixed["compat_picks"] = list(res.get("picks") or []) if isinstance(res, dict) else []
    except Exception:
        fixed["compat_picks"] = []
    fixed["artifact_version"] = "v2"
    return fixed
