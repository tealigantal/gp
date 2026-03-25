from __future__ import annotations

"""
Unified time/trading-day policy helpers.

Defines:
  - detect_cutoff(now) -> "INTRADAY" | "EOD"
  - is_artifact_valid(artifact, now)

These helpers are deterministic and centralize the 15:05 close logic
in configured timezone (default Asia/Shanghai).
"""

from datetime import datetime, time as _time, timezone
from typing import Any, Dict, Optional

from ..core.config import load_config


def _now_tz() -> datetime:
    cfg = load_config()
    try:
        import zoneinfo

        tz = zoneinfo.ZoneInfo(getattr(cfg, "timezone", "Asia/Shanghai"))
    except Exception:
        tz = timezone.utc
    return datetime.now(tz=tz)


def detect_cutoff(now: Optional[datetime] = None) -> str:
    dt = now or _now_tz()
    # Close threshold 15:05 local time
    cut = _time(15, 5)
    return "EOD" if dt.time() >= cut else "INTRADAY"


def _date_only(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    x = str(s).replace("-", "").strip()
    if len(x) >= 8 and x[:8].isdigit():
        return f"{x[:4]}-{x[4:6]}-{x[6:8]}"
    try:
        # last resort
        return str(s).split("T", 1)[0]
    except Exception:
        return None


def is_artifact_valid(artifact: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    dt = now or _now_tz()
    cutoff = str(artifact.get("data_cutoff") or "").upper() or "INTRADAY"
    as_of = _date_only(artifact.get("as_of"))
    if not as_of:
        return False
    today = _date_only(dt.date().isoformat())
    if as_of != today:
        return False
    # Same day: intraday becomes invalid after close; EOD valid only after close and until day changes
    if cutoff == "INTRADAY":
        return detect_cutoff(dt) == "INTRADAY"
    # EOD: only valid after close; if before close, prefer intraday rebuild
    return detect_cutoff(dt) == "EOD"

