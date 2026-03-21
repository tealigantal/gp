from __future__ import annotations

from typing import Any, Dict, List
import json
from pathlib import Path

from ..core.paths import store_dir


def event_stats_path(strategy: str) -> Path:
    base = store_dir() / "validation" / "event_stats"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{strategy}.json"


def compute_event_stats(returns_d3: List[float], returns_d5: List[float], returns_d10: List[float]) -> Dict[str, Any]:
    def _mean(xs: List[float]) -> float:
        return (sum(xs) / max(1, len(xs))) if xs else 0.0

    def _win_rate(xs: List[float]) -> float:
        return (sum(1 for x in xs if x > 0) / max(1, len(xs))) if xs else 0.0

    return {
        "sample_size": min(len(returns_d3), len(returns_d5), len(returns_d10)),
        "d3_mean": _mean(returns_d3),
        "d5_mean": _mean(returns_d5),
        "d10_mean": _mean(returns_d10),
        "win_rate_d5": _win_rate(returns_d5),
    }


def save_event_stats(strategy: str, stats: Dict[str, Any]) -> None:
    p = event_stats_path(strategy)
    p.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


def load_event_stats(strategy: str) -> Dict[str, Any]:
    p = event_stats_path(strategy)
    if not p.exists():
        return {"available": False, "sample_size": 0}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        obj["available"] = True
        return obj
    except Exception:
        return {"available": False, "sample_size": 0}

