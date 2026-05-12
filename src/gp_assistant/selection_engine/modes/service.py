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
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ...core.paths import store_dir, data_dir


def canonicalize_ts_code(raw: str) -> Tuple[str, str, str]:
    value = str(raw or "").strip().upper()
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) >= 6:
        code6 = digits[-6:]
    else:
        code6 = digits.zfill(6) if digits else ""
    suffix = ""
    if value.endswith(".SH") or value.startswith("SH"):
        suffix = "SH"
    elif value.endswith(".SZ") or value.startswith("SZ"):
        suffix = "SZ"
    elif code6.startswith(("5", "6", "9")):
        suffix = "SH"
    elif code6:
        suffix = "SZ"
    ts_code = f"{code6}.{suffix}" if code6 and suffix else code6
    display = ts_code or value
    return ts_code, code6, display


def _parse_date_keyword(d: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Validate and normalize incoming date keyword.

    Returns (normalized, error_reason) where normalized is one of:
    - "latest"
    - YYYYMMDD
    and error_reason is a string code when invalid.
    """
    if d is None or str(d).strip() == "":
        return ("latest", None)
    s = str(d).strip().lower()
    if s in {"latest", "today"}:
        if s == "today":
            from datetime import datetime
            return (datetime.now().strftime("%Y%m%d"), None)
        return ("latest", None)
    # strict validation: only digits and dash up to len 10
    if any(ch in s for ch in ("..", "/", "\\")):
        return (None, "INVALID_DATE")
    if not all((c.isdigit() or c == '-') for c in s):
        return (None, "INVALID_DATE")
    if len(s) > 10:
        return (None, "INVALID_DATE")
    # normalize to YYYYMMDD or keep as-is for lookup
    if len(s) == 8 and s.isdigit():
        return (s, None)
    if len(s) == 10 and s[4] == '-' and s[7] == '-':
        return (s[0:4] + s[5:7] + s[8:10], None)
    # allow 7/9 lengths degrade
    return (None, "INVALID_DATE")


def _read_reco_file(date: Optional[str]) -> Dict[str, Any] | None:
    base = store_dir() / "recommend"
    norm, _ = _parse_date_keyword(date)
    if not norm or norm == "latest":
        p = base / "latest.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    # try YYYYMMDD then YYYY-MM-DD
    cand: List[Path] = [base / f"{norm}.json"]
    try:
        if len(str(norm)) == 8 and str(norm).isdigit():
            yyyy, mm, dd = str(norm)[0:4], str(norm)[4:6], str(norm)[6:8]
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

def _normalize_to_v1(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Return {picks, meta} from mixed/legacy shapes.

    - Accepts legacy top-level fields or already v1 shape (with meta)
    - Ensures debug.degrade_reasons exists; maps legacy `reasons`
    - Canonicalizes pick symbols to include ts_code/code/symbol
    - Enforces 'EMPTY_PICKS' degraded state if tradeable and empty picks
    """
    if not isinstance(obj, dict):
        return {"picks": [], "meta": {"as_of": None, "as_of_ts": None, "timezone": "Asia/Shanghai", "tradeable": False, "message": "invalid", "disclaimer": None, "stage": None, "debug": {"mode": "service", "degraded": True, "degrade_reasons": [{"reason_code": "INVALID_PAYLOAD"}]}}}

    # Already v1
    if isinstance(obj.get("meta"), dict) and isinstance(obj.get("picks"), list):
        picks = list(obj.get("picks") or [])
        meta = dict(obj.get("meta") or {})
    else:
        # Legacy -> map to v1
        picks = list(obj.get("picks") or [])
        meta = {
            "as_of": obj.get("as_of"),
            "as_of_ts": obj.get("as_of_ts"),
            "timezone": obj.get("timezone", "Asia/Shanghai"),
            "tradeable": bool(obj.get("tradeable", True)),
            "message": obj.get("message"),
            "disclaimer": obj.get("disclaimer"),
            "stage": obj.get("stage"),
            "debug": obj.get("debug") or {},
        }

    # Normalize debug keys
    dbg = meta.get("debug") or {}
    if not isinstance(dbg, dict):
        dbg = {}
    if "degrade_reasons" not in dbg and isinstance(dbg.get("reasons"), list):
        dbg["degrade_reasons"] = list(dbg["reasons"])  # type: ignore[index]
    dbg.setdefault("degrade_reasons", [])
    dbg.setdefault("degraded", False)
    dbg.setdefault("mode", "service")
    meta["debug"] = dbg

    # Canonicalize picks symbols
    norm_picks: List[Dict[str, Any]] = []
    for it in picks:
        if not isinstance(it, dict):
            continue
        raw = it.get("ts_code") or it.get("symbol") or it.get("code") or ""
        ts, code6, disp = canonicalize_ts_code(str(raw))
        out = dict(it)
        out["ts_code"] = ts
        out["code"] = code6
        out.setdefault("symbol", disp)
        norm_picks.append(out)
    picks = norm_picks

    # Enforce empty picks degraded state if tradeable is True
    if bool(meta.get("tradeable", True)) and not picks:
        dr = list(meta["debug"].get("degrade_reasons") or [])
        dr.append({"reason_code": "EMPTY_PICKS", "detail": {}})
        meta["debug"]["degrade_reasons"] = dr
        meta["debug"]["degraded"] = True
        # keep legacy redundancy
        meta["debug"]["reasons"] = dr

    return {"picks": picks, "meta": meta}


def _load_trade_calendar() -> Optional[pd.DataFrame]:
    try:
        p = data_dir() / "raw" / "trade_calendar.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            # normalize columns
            if "cal_date" in df.columns and "is_open" in df.columns:
                df = df[["cal_date", "is_open"]].copy()
                df["cal_date"] = (
                    df["cal_date"]
                    .astype(str)
                    .str.strip()
                    .str.replace("-", "", regex=False)
                    .str.slice(0, 8)
                )
                df = df[df["cal_date"].str.fullmatch(r"\d{8}", na=False)]
                df["is_open"] = pd.to_numeric(df["is_open"], errors="coerce").fillna(0).astype(int)
                df["is_open"] = (df["is_open"] == 1).astype(int)
                df = df.drop_duplicates(subset=["cal_date"], keep="last").sort_values("cal_date").reset_index(drop=True)
                return df if not df.empty else None
    except Exception:
        return None
    return None


def run(
    date: Optional[str] = None,
    topk: int = 3,
    universe: str = "auto",
    symbols: Optional[List[str]] = None,
    risk_profile: str = "normal",
) -> Dict[str, Any]:
    norm, err = _parse_date_keyword(date)
    if err:
        # Minimal v1 degraded output
        return {
            "picks": [],
            "meta": {
                "as_of": None,
                "as_of_ts": None,
                "timezone": "Asia/Shanghai",
                "tradeable": False,
                "message": "service_recommend_invalid_date",
                "disclaimer": None,
                "stage": None,
                "debug": {"mode": "service", "degraded": True, "degrade_reasons": [{"reason_code": "INVALID_DATE", "detail": {"date": date}}]},
            },
        }

    obj = _read_reco_file(norm or "latest")
    if not isinstance(obj, dict):
        # degraded payload v1
        return {
            "picks": [],
            "meta": {
                "as_of": None,
                "as_of_ts": None,
                "timezone": "Asia/Shanghai",
                "tradeable": False,
                "message": "service_recommend_missing",
                "disclaimer": None,
                "stage": None,
                "debug": {"mode": "service", "degraded": True, "degrade_reasons": [{"reason_code": "SERVICE_RECO_MISSING", "detail": {"date": date or "latest"}}]},
            },
        }

    # normalize to v1
    out = _normalize_to_v1(obj)

    # limit picks to topk if provided
    if isinstance(out.get("picks"), list) and isinstance(topk, int) and topk > 0:
        out["picks"] = out.get("picks", [])[:topk]

    # Trading-day handling
    try:
        cal = _load_trade_calendar()
        if cal is not None:
            # requested_date vs resolved
            req = (date or "latest").strip() if date is not None else "latest"
            today = pd.Timestamp.today(tz=None).strftime("%Y%m%d")
            if req in {"latest", "today", ""}:
                # if today is non-trading day, annotate debug with resolved_date=next open (do not change tradeable)
                row = cal[cal["cal_date"] >= today]
                next_open = None
                if not row.empty:
                    sub = row[row["is_open"] == 1]
                    if not sub.empty:
                        next_open = str(sub.iloc[0]["cal_date"])  # first open on/after today
                if next_open and isinstance(out.get("meta"), dict):
                    dbg = out["meta"].setdefault("debug", {})
                    if isinstance(dbg, dict):
                        dbg.setdefault("requested_date", req)
                        dbg.setdefault("resolved_date", next_open)
            else:
                # explicit date
                dnorm = req.replace("-", "") if len(req) == 10 and req[4] == '-' else req
                row = cal[cal["cal_date"] == dnorm]
                if not row.empty and int(row.iloc[0]["is_open"]) != 1:
                    # Explicit date is a non-trading day: record in debug only; do not force non-tradeable
                    dbg = out["meta"].setdefault("debug", {})
                    if isinstance(dbg, dict):
                        dbg.setdefault("requested_date", req)
                        dbg.setdefault("resolved_date", dnorm)
    except Exception:
        pass

    return out
