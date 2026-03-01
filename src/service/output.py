from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Dict, List, Optional, Tuple

from .io_utils import write_json_atomic


def _ensure_degrade(debug: Dict[str, Any], *, reason_code: str, detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    dbg = dict(debug or {})
    # normalize degrade_reasons
    reasons: List[Dict[str, Any]] = []
    exist = dbg.get("degrade_reasons") or dbg.get("reasons") or []
    if isinstance(exist, list):
        reasons.extend([r for r in exist if isinstance(r, dict)])
    if reason_code:
        reasons.append({"reason_code": reason_code, "detail": detail or {}})
    dbg["degraded"] = True
    dbg["degrade_reasons"] = reasons
    # keep legacy redundancy to ease consumers that still look at `reasons`
    dbg["reasons"] = reasons
    return dbg


def build_reco_json(
    *,
    as_of_date: str,
    as_of_ts: str,
    stage: str,
    picks: List[Dict[str, Any]],
    tradeable: bool = True,
    message: str = "",
    disclaimer: str = "For research only; not investment advice.",
    timezone: str = "Asia/Shanghai",
    debug: Optional[Dict[str, Any]] = None,
    paths_meta: Optional[Dict[str, str]] = None,
    empty_picks_stats: Optional[Tuple[int, int]] = None,
) -> Dict[str, Any]:
    """Build recommendation JSON object in v1 contract: {picks, meta}.

    - meta fields: tradeable, as_of, as_of_ts, stage, timezone, disclaimer, message, debug{degraded,degrade_reasons,mode}, paths
    - picks: list of pick objects (already canonicalized by caller)
    - Enforce: if tradeable and empty picks -> degraded with EMPTY_PICKS
    """
    dbg = dict(debug or {"mode": "service", "degraded": False, "degrade_reasons": []})
    # legacy map: accept `reasons` input but write `degrade_reasons`
    if "degrade_reasons" not in dbg and isinstance(dbg.get("reasons"), list):
        dbg["degrade_reasons"] = list(dbg.get("reasons"))
    if "reasons" not in dbg and isinstance(dbg.get("degrade_reasons"), list):
        dbg["reasons"] = list(dbg.get("degrade_reasons"))

    if tradeable and not picks:
        cand_count = 0
        topk = 0
        if empty_picks_stats:
            cand_count, topk = empty_picks_stats
        dbg = _ensure_degrade(
            dbg,
            reason_code="EMPTY_PICKS",
            detail={"candidate_count": cand_count, "topk": topk},
        )

    if paths_meta:
        pm = {k: str(v) for k, v in paths_meta.items()}
        dbg.setdefault("paths", pm)
        if not isinstance(dbg.get("paths"), dict):
            dbg["paths"] = pm

    meta: Dict[str, Any] = {
        "as_of": as_of_date,
        "as_of_ts": as_of_ts,
        "timezone": timezone,
        "tradeable": bool(tradeable),
        "message": message,
        "disclaimer": disclaimer,
        "stage": stage,
        "debug": dbg,
    }
    return {"picks": picks, "meta": meta}


def write_reco_json(target: Path, obj: Dict[str, Any]) -> None:
    """Atomic write for recommendation JSON files.

    Writes to `<name>.tmp` and atomically replaces the destination.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(target, obj)
