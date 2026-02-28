from __future__ import annotations

"""
Service-backed recommend mode.

Reads store/recommend/latest.json (or YYYYMMDD.json) and adapts to the
RecommendationCard-compatible payload expected by the chat orchestrator.

On missing/invalid file, returns a degraded payload with empty picks and
debug.degrade_reasons including SERVICE_RECO_MISSING.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...core.paths import store_dir


def _read_reco_file(date: Optional[str]) -> Dict[str, Any] | None:
    base = store_dir() / "recommend"
    if not date or date == "latest":
        p = base / "latest.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    # try YYYYMMDD then YYYY-MM-DD
    cand: List[Path] = [base / f"{date}.json"]
    try:
        if len(str(date)) == 8 and str(date).isdigit():
            yyyy, mm, dd = str(date)[0:4], str(date)[4:6], str(date)[6:8]
            cand.append(base / f"{yyyy}-{mm}-{dd}.json")
    except Exception:
        pass
    for p in cand:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def _ensure_card_shape(obj: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(obj or {})
    # required top-level fields expected by compact/meta helpers
    out.setdefault("as_of", None)
    out.setdefault("themes", [])
    out.setdefault("mainline", {"sectors": []})
    out.setdefault("mover_hints", [])
    out.setdefault("picks", [])
    # debug shape
    dbg = out.get("debug") or {}
    if not isinstance(dbg, dict):
        dbg = {}
    dbg.setdefault("mode", "service")
    # normalize key name to degrade_reasons
    if "degrade_reasons" not in dbg:
        if isinstance(dbg.get("reasons"), list):
            dbg["degrade_reasons"] = dbg.get("reasons")
        else:
            dbg.setdefault("degrade_reasons", [])
    dbg.setdefault("degraded", False)
    out["debug"] = dbg
    # data_status minimal skeleton
    ds = out.get("data_status")
    if not isinstance(ds, dict):
        ds = {}
    ds.setdefault("snapshot", {"ok": True, "source": "service_json", "rows": len(out.get("picks") or []), "elapsed_sec": None, "cache": "file", "as_of_ts": None})
    ds.setdefault("themes", {"ok": True, "source": "service_json", "attempted": [], "error": None, "as_of_ts": None})
    ds.setdefault("daily", {"ok": True, "symbols_ok": len(out.get("picks") or []), "symbols_fail": 0, "error_summary": None})
    out["data_status"] = ds
    return out


def run(
    date: Optional[str] = None,
    topk: int = 3,
    universe: str = "auto",
    symbols: Optional[List[str]] = None,
    risk_profile: str = "normal",
) -> Dict[str, Any]:
    obj = _read_reco_file(date or "latest")
    if not isinstance(obj, dict):
        # degraded payload
        return {
            "picks": [],
            "as_of": None,
            "themes": [],
            "mainline": {"sectors": []},
            "mover_hints": [],
            "message": "service_recommend_missing",
            "debug": {
                "mode": "service",
                "degraded": True,
                "degrade_reasons": [
                    {"reason_code": "SERVICE_RECO_MISSING", "detail": {"date": date or "latest"}}
                ],
            },
            "data_status": {
                "snapshot": {"ok": False, "source": None, "rows": 0, "elapsed_sec": None, "cache": "none", "as_of_ts": None, "error": "SERVICE_RECO_MISSING"},
                "themes": {"ok": False, "source": None, "attempted": [], "error": "SERVICE_RECO_MISSING", "as_of_ts": None},
                "daily": {"ok": False, "symbols_ok": 0, "symbols_fail": 0, "error_summary": "SERVICE_RECO_MISSING"},
            },
        }

    # limit picks to topk if provided
    if isinstance(obj.get("picks"), list) and isinstance(topk, int) and topk > 0:
        obj = dict(obj)
        obj["picks"] = obj.get("picks", [])[:topk]

    return _ensure_card_shape(obj)

