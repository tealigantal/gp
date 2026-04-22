from __future__ import annotations

from datetime import datetime
from typing import Any, Dict


def is_run_valid_for_operation(artifact: Dict[str, Any], now: datetime, operation: str = "recommend") -> bool:
    cutoff = str(artifact.get("data_cutoff") or "").upper()
    as_of = str(artifact.get("as_of") or artifact.get("trading_date") or "")
    run_day = None
    try:
        run_day = datetime.fromisoformat(as_of).date()
    except Exception:
        run_day = None
    if cutoff == "INTRADAY" and run_day is not None and now.date() == run_day and (now.hour > 15 or (now.hour == 15 and now.minute >= 0)):
        return False
    return True
