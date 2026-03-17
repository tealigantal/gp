from __future__ import annotations

"""
Minimal refresh service (Phase 1).

Recomputes trade plan/bands for given symbols using latest data via recommend.runner
in symbols mode (no reuse of previous artifacts).
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from ..recommend.runner import run as recommend_run


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def refresh_symbols(symbols: List[str], *, as_of: Optional[str] = None) -> Dict[str, Any]:
    syms = [str(s).strip() for s in (symbols or []) if str(s).strip()]
    if not syms:
        return {"ok": False, "error": "NO_SYMBOLS"}
    try:
        res = recommend_run(universe="symbols", symbols=syms, date=as_of, topk=len(syms))
        # Minimal normalized envelope for Phase 1
        return {
            "ok": True,
            "as_of": res.get("as_of"),
            "run_id": res.get("as_of") or res.get("run_id") or _now_iso(),
            "symbols": syms,
            "picks": res.get("picks") or [],
            "tradeable": res.get("tradeable"),
            "diagnostics": {
                "degraded": bool((res.get("debug") or {}).get("degraded") is True),
                "degrade_reasons": (res.get("debug") or {}).get("degrade_reasons") or [],
            },
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"REFRESH_FAILED:{e}"}

