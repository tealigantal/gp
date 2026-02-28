from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Dict, List


def build_reco_json(
    *,
    as_of: str,
    stage: str,
    picks: List[Dict[str, Any]],
    tradeable: bool = True,
    message: str = "",
    disclaimer: str = "For research only; not investment advice.",
    timezone: str = "Asia/Shanghai",
    debug: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "as_of": as_of,
        "timezone": timezone,
        "tradeable": bool(tradeable),
        "message": message,
        "disclaimer": disclaimer,
        "stage": stage,
        "picks": picks,
        "debug": debug or {"mode": "service", "degraded": False, "reasons": []},
    }


def write_reco_json(target: Path, obj: Dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

