from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Dict, List, Optional

from .io_utils import write_json_atomic


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
) -> Dict[str, Any]:
    """Build recommendation JSON object for service publish.

    - as_of_date: YYYYMMDD
    - as_of_ts:   YYYYMMDD HH:MM:SS (local, Asia/Shanghai by default)
    - stage:      preopen | intraday | close
    """
    obj: Dict[str, Any] = {
        "as_of": as_of_date,
        "as_of_ts": as_of_ts,
        "timezone": timezone,
        "tradeable": bool(tradeable),
        "message": message,
        "disclaimer": disclaimer,
        "stage": stage,
        "picks": picks,
        "debug": debug or {"mode": "service", "degraded": False, "reasons": []},
    }
    return obj


def write_reco_json(target: Path, obj: Dict[str, Any]) -> None:
    """Atomic write for recommendation JSON files.

    Writes to `<name>.tmp` and atomically replaces the destination.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(target, obj)
