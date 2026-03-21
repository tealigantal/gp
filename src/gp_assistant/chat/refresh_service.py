from __future__ import annotations

"""
Minimal refresh service (Phase 1).

Recomputes trade plan/bands for given symbols using latest data via recommend.runner
in symbols mode (no reuse of previous artifacts).
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from ..recommend.refresh_service import refresh_symbols_v2


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def refresh_symbols(symbols: List[str], *, as_of: Optional[str] = None) -> Dict[str, Any]:
    syms = [str(s).strip() for s in (symbols or []) if str(s).strip()]
    if not syms:
        return {"ok": False, "error": "NO_SYMBOLS"}
    try:
        v2 = refresh_symbols_v2(syms, as_of=as_of)
        # Thin compatibility layer for existing chat card consumers
        out = {
            "ok": bool(v2.get("ok", True)),
            "as_of": v2.get("as_of"),
            "run_id": v2.get("run_id") or v2.get("as_of") or _now_iso(),
            "symbols": syms,
            # Use compat picks provided by canonical refresh to avoid re‑implementing logic here
            "picks": list(v2.get("compat_picks") or []),
            "tradeable": v2.get("tradeable"),
            "diagnostics": {
                "degraded": bool(v2.get("degraded") is True),
                "degrade_reasons": v2.get("errors") or [],
            },
        }
        return out
    except Exception:  # noqa: BLE001
        # sanitize: do not leak internal exception string
        return {"ok": False, "error": "refresh_unavailable"}
