from __future__ import annotations

from typing import Any, Dict, List
import json
from pathlib import Path

from ..core.paths import store_dir


def walkforward_path(strategy: str) -> Path:
    base = store_dir() / "validation" / "walkforward"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{strategy}.json"


def compute_walkforward_summary(series: List[float], window: int = 20, recent_k: int = 3) -> Dict[str, Any]:
    """
    Simple rolling-window means; returns overall windows, stability flag and recent window rank.
    """
    windows: List[float] = []
    n = len(series)
    if window <= 0:
        window = 20
    for i in range(0, max(0, n - window + 1)):
        w = series[i:i + window]
        windows.append(sum(w) / len(w))
    stable = bool(windows and windows[-1] > 0.0)
    # rank recent among last recent_k windows (higher is better)
    recent = windows[-recent_k:] if windows else []
    recent_rank = None
    if recent:
        rec = recent[-1]
        recent_rank = sorted(recent, reverse=True).index(rec) + 1
    return {
        "windows": windows,
        "stable": stable,
        "recent_rank": recent_rank,
    }


def save_walkforward(strategy: str, summary: Dict[str, Any]) -> None:
    p = walkforward_path(strategy)
    p.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def load_walkforward(strategy: str) -> Dict[str, Any]:
    p = walkforward_path(strategy)
    if not p.exists():
        return {"available": False, "windows": []}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        obj["available"] = True
        return obj
    except Exception:
        return {"available": False, "windows": []}

