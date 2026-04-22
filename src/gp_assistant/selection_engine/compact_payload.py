from __future__ import annotations

from typing import Any, Dict
from ..core.strict import is_strict


def compact_recommend_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Compact Recommend payload for API responses.

    Keeps only:
    - as_of, timezone, env, themes, picks, tradeable, message, execution_checklist, disclaimer
    - debug.{degraded,degrade_reasons,advisories,mode,dev_source}
    """
    # Accept v1 shape (picks + meta) or legacy flat shape
    if isinstance(payload.get("meta"), dict):
        meta = dict(payload.get("meta") or {})
        out: Dict[str, Any] = {k: meta.get(k) for k in ["as_of", "timezone", "env", "themes", "mainline", "mover_hints", "tradeable", "message", "execution_checklist", "disclaimer"] if k in meta}
        out["picks"] = payload.get("picks", [])
        dbg = meta.get("debug") or {}
    else:
        keep_keys = {
            "as_of",
            "timezone",
            "env",
            "themes",
            "mainline",
            "mover_hints",
            "picks",
            "tradeable",
            "message",
            "execution_checklist",
            "disclaimer",
        }
        out = {k: payload.get(k) for k in keep_keys if k in payload}
        dbg = payload.get("debug") or {}
    if isinstance(dbg, dict):
        slim = {}
        for k in ("degraded", "degrade_reasons", "advisories", "mode", "dev_source"):
            if k in dbg:
                slim[k] = dbg.get(k)
        if slim:
            out["debug"] = slim
    # attach schema/data_status if present
    out["schema_version"] = 1
    out["strict_output"] = True if is_strict() else False
    if isinstance(payload.get("data_status"), dict):
        out["data_status"] = payload.get("data_status")
    return out


def compact_recommend_meta(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Meta subset for event payloads (no picks)."""
    # Accept v1 shape (payload.meta) or legacy
    if isinstance(payload.get("meta"), dict):
        meta = dict(payload.get("meta") or {})
        keep = ["as_of", "timezone", "env", "themes", "mainline", "mover_hints", "tradeable", "message", "execution_checklist", "disclaimer"]
        out: Dict[str, Any] = {k: meta.get(k) for k in keep if k in meta}
        dbg = meta.get("debug") or {}
    else:
        keep_keys = {
            "as_of",
            "timezone",
            "env",
            "themes",
            "mainline",
            "mover_hints",
            "tradeable",
            "message",
            "execution_checklist",
            "disclaimer",
        }
        out = {k: payload.get(k) for k in keep_keys if k in payload}
        dbg = payload.get("debug") or {}
    if isinstance(dbg, dict):
        slim = {}
        for k in ("degraded", "degrade_reasons", "advisories", "mode", "dev_source"):
            if k in dbg:
                slim[k] = dbg.get(k)
        if slim:
            out["debug"] = slim
    out["schema_version"] = 1
    out["strict_output"] = True if is_strict() else False
    if isinstance(payload.get("data_status"), dict):
        out["data_status"] = payload.get("data_status")
    return out
