from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ..core.strict import is_strict


def _float_or_none(v: Any) -> float | None:
    try:
        x = float(v)
        if x == 0.0:
            return None
        return x
    except Exception:
        return None


def normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Enforce strict output invariants on the recommendation payload.

    - Missing numeric fields must be None (not 0.0)
    - Picks missing last_close or bands are dropped when strict=1; reasons stored in debug.dropped_picks
    - Do not fabricate themes or hints
    """
    strict = is_strict()
    dbg = payload.setdefault("debug", {}) if isinstance(payload.get("debug"), dict) else payload.setdefault("debug", {})
    dropped: List[Dict[str, Any]] = []
    picks = payload.get("picks") if isinstance(payload, dict) else None
    if isinstance(picks, list):
        new_picks = []
        for it in picks:
            if not isinstance(it, dict):
                continue
            # normalize last_close/last_date if present else keep None
            if "last_close" in it and it["last_close"] in (0.0, 0, "0", "0.0"):
                it["last_close"] = None
            # sanitize trade_plan bands zeros
            tp = it.get("trade_plan") or {}
            bands = (tp.get("bands") or {}) if isinstance(tp, dict) else {}
            if bands:
                for k in list(bands.keys()):
                    v = _float_or_none(bands.get(k))
                    if v is None:
                        bands.pop(k, None)
                    else:
                        bands[k] = v
                if not bands:
                    tp["bands"] = {}
            # strict drop rules
            need_drop = False
            reason = None
            if strict:
                if it.get("last_close") is None:
                    need_drop = True; reason = "missing_last_close"
                elif not bands:
                    need_drop = True; reason = "missing_bands"
            if need_drop:
                dropped.append({"symbol": it.get("symbol"), "reason": reason})
                continue
            new_picks.append(it)
        payload["picks"] = new_picks
    if dropped:
        dbg["dropped_picks"] = dropped
    return payload

