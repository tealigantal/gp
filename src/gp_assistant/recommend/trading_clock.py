from __future__ import annotations

"""
Unified trading-time helpers for Asia/Shanghai.

This module centralizes all time-related decisions used by the mainline:
- get_now_local() -> timezone-aware now
- get_market_phase(now)
- resolve_effective_trading_date(now)
- detect_cutoff_for_now(now) -> INTRADAY|EOD
- infer_cutoff_from_artifact_meta(artifact)
- is_run_valid_for_operation(artifact, now, operation)

Notes:
- Trading day model is weekday-only (Mon–Fri). TODO: integrate real holiday calendar.
- 15:05 local is the only close threshold and must not be re-implemented elsewhere.
"""

from datetime import datetime, time as _time, timedelta
from typing import Any, Dict, Optional

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


# ---- Core time helpers ----


def get_now_local() -> datetime:
    tz = ZoneInfo("Asia/Shanghai") if ZoneInfo else None
    return datetime.now(tz=tz)


def _is_weekday(d: datetime) -> bool:
    return d.weekday() < 5


def _prev_weekday(d: datetime) -> datetime:
    x = d
    while not _is_weekday(x):
        x = x - timedelta(days=1)
    return x


def get_market_phase(now: Optional[datetime] = None) -> str:
    dt = (now or get_now_local())
    local_t = dt.time()
    if not _is_weekday(dt):
        return "NON_TRADING"
    # A-share rough session windows (simplified):
    # PREOPEN 09:00–09:30; INTRADAY 09:30–15:00; POSTCLOSE_READY 15:00+; cutoff uses 15:05
    if local_t < _time(9, 30):
        return "PREOPEN"
    if local_t < _time(15, 0):
        return "INTRADAY"
    return "POSTCLOSE_READY"


def resolve_effective_trading_date(now: Optional[datetime] = None) -> str:
    dt = (now or get_now_local())
    if _is_weekday(dt):
        # trading day phases map to the same effective trading date
        return dt.date().isoformat()
    # weekend/holidays: use the most recent trading day (weekday-only for now)
    return _prev_weekday(dt).date().isoformat()


def detect_cutoff_for_now(now: Optional[datetime] = None) -> str:
    dt = (now or get_now_local())
    phase = get_market_phase(dt)
    if phase in {"PREOPEN", "INTRADAY"}:
        return "INTRADAY"
    # POSTCLOSE_READY or NON_TRADING -> EOD view
    return "EOD"


# ---- Artifact meta interpretation ----


def _safe_date_from_any(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        # accept both YYYY-MM-DD and compact YYYYMMDD
        t = str(s).strip().replace("/", "-")
        if len(t) >= 8 and t[:8].isdigit():
            return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    except Exception:
        pass
    try:
        return str(s).split("T", 1)[0]
    except Exception:
        return None


def _parse_as_of_ts(ts: Optional[str]) -> tuple[Optional[str], Optional[tuple[int, int]]]:
    if not ts:
        return None, None
    try:
        # Normalize forms like YYYY-MM-DDTHH:MM:SS or YYYYMMDD HH:MM:SS
        s = str(ts).strip().replace("/", "-")
        if "T" in s:
            d, t = s.split("T", 1)
        elif " " in s:
            d, t = s.split(" ", 1)
        else:
            # date only
            d, t = s, ""
        d = _safe_date_from_any(d)
        hhmm = None
        if t:
            # HH:MM[:SS]
            parts = t.split(":")
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                hhmm = (int(parts[0]), int(parts[1]))
        return d, hhmm
    except Exception:
        return None, None


def infer_cutoff_from_artifact_meta(artifact: Dict[str, Any]) -> str:
    # 1) explicit field wins
    cut = str(artifact.get("data_cutoff") or "").upper().strip()
    if cut in {"INTRADAY", "EOD"}:
        return cut
    # 2) trading_date/as_of_ts evidence
    trading_date = _safe_date_from_any(artifact.get("trading_date") or artifact.get("as_of"))
    ts_date, hhmm = _parse_as_of_ts(artifact.get("as_of_ts") or artifact.get("snapshot_id"))
    if trading_date and ts_date:
        if ts_date > trading_date:
            return "EOD"  # snapshot after trading_date implies finalized
        if ts_date == trading_date and hhmm is not None:
            hh, mm = hhmm
            # A conservative inference: before 15:05 -> intraday; otherwise EOD
            if (hh, mm) < (15, 5):
                return "INTRADAY"
            return "EOD"
    # 3) historical artifact date without precise ts -> EOD by default
    if trading_date:
        return "EOD"
    # 4) fallback: conservative EOD
    return "EOD"


def is_run_valid_for_operation(artifact: Dict[str, Any], now: Optional[datetime], operation: str) -> bool:
    if not isinstance(artifact, dict) or not artifact:
        return False
    op = (operation or "recommend").lower()

    art_td = _safe_date_from_any(artifact.get("trading_date") or artifact.get("as_of"))
    if not art_td:
        return False
    cut = infer_cutoff_from_artifact_meta(artifact)

    dt = (now or get_now_local())
    now_td = resolve_effective_trading_date(dt)
    phase = get_market_phase(dt)

    # Follow-up family always valid for referenced runs irrespective of current day/phase
    if op in {"followup", "pick_detail", "compare", "exit_decision", "run_diff"}:
        return True

    # Core recommendation/refresh validity
    if cut == "INTRADAY":
        # Intraday run is only valid pre-close on its trading day
        if art_td != now_td:
            return False
        return phase in {"PREOPEN", "INTRADAY"}

    # EOD runs (finalized for the day)
    if art_td == now_td:
        # same trading date -> valid in postclose and non-trading too
        return True
    # If we are on the next trading day PREOPEN, allow using previous EOD as baseline
    if phase == "PREOPEN":
        # Accept immediately previous trading day's EOD as baseline
        return True
    # INTRADAY of a new day -> encourage refresh for recommendation
    return False

