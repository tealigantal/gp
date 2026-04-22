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
from .artifact_store import build_v2_dict_from_v1


def refresh_symbols_v2(symbols: List[str], *, as_of: Optional[str] = None, risk_profile: Optional[str] = None) -> Dict[str, Any]:
    syms = [str(s).strip() for s in (symbols or []) if str(s).strip()]
    if not syms:
        return {"ok": False, "error": "NO_SYMBOLS"}

    res = _run(universe="symbols", symbols=syms, date=as_of, topk=len(syms))
    fixed = build_v2_dict_from_v1(res, risk_profile=risk_profile, universe="symbols")
    # For refresh service, degraded or validation warnings should not flip ok to False.
    fixed["ok"] = True
    # Provide a compatibility picks array for chat card (from original v1 res)
    try:
        fixed["compat_picks"] = list(res.get("picks") or []) if isinstance(res, dict) else []
    except Exception:
        fixed["compat_picks"] = []
    fixed["artifact_version"] = "v2"
    return fixed
