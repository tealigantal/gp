from __future__ import annotations

from typing import Dict, List, Optional

from ..selection_engine.refresh_service import refresh_symbols_v2


def refresh_symbols(symbols: List[str], *, as_of: Optional[str] = None, risk_profile: Optional[str] = None) -> Dict[str, object]:
    out = refresh_symbols_v2(symbols, as_of=as_of, risk_profile=risk_profile)
    picks = []
    for item in out.get("items") or []:
        if not isinstance(item, dict):
            continue
        picks.append({
            "symbol": item.get("symbol"),
            "score": item.get("final_score"),
            "trade_plan": {
                "bands": {
                    "S1": item.get("entry_min"),
                    "R1": (item.get("take_profit") or [None])[0],
                }
            },
        })
    return {"ok": bool(out.get("ok", True)), "symbols": symbols, "picks": picks, "items": out.get("items") or []}
