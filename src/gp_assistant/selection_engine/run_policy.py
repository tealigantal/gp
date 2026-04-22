from __future__ import annotations

from datetime import datetime


def detect_cutoff(now: datetime | None = None) -> str:
    dt = now or datetime.now()
    return "EOD" if (dt.hour > 15 or (dt.hour == 15 and dt.minute >= 0)) else "INTRADAY"
