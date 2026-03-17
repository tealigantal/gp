from __future__ import annotations

from typing import Any, Dict
import json
from pathlib import Path

from ..core.paths import store_dir
from .event_stats import load_event_stats
from .walkforward_stats import load_walkforward


def strategy_health_path(strategy: str) -> Path:
    base = store_dir() / "validation" / "strategy_health"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{strategy}.json"


def compute_strategy_health(strategy: str) -> Dict[str, Any]:
    """Combine event stats + walk-forward to produce health and reasons.

    Simple deterministic rule-set:
    - killed: win_rate_d5 < 0.35 AND last window <= -0.02
    - degraded: win_rate_d5 < 0.45 OR last window <= -0.01
    - warning: last window slightly negative (<= 0)
    - healthy: otherwise
    """
    es = load_event_stats(strategy)
    wf = load_walkforward(strategy)
    wr = float(es.get("win_rate_d5") or 0.0)
    last_win = 0.0
    try:
        ws = wf.get("windows") or []
        last_win = float(ws[-1]) if ws else 0.0
    except Exception:
        last_win = 0.0
    status = "healthy"
    reasons = []
    if wr < 0.35 and last_win <= -0.02:
        status = "killed"; reasons.extend(["low_win_rate", "negative_recent"])
    elif wr < 0.45 or last_win <= -0.01:
        status = "degraded"; reasons.extend(["low_win_rate" if wr < 0.45 else "negative_recent"])
    elif last_win <= 0.0:
        status = "warning"; reasons.append("flat_recent")
    return {
        "status": status,
        "reason_codes": reasons,
        "paper_trade_summary": {},
        "event_summary": {k: es.get(k) for k in ["sample_size", "d3_mean", "d5_mean", "d10_mean", "win_rate_d5"]},
        "walkforward_summary": {k: wf.get(k) for k in ["stable", "recent_rank", "windows"]},
    }


def save_strategy_health(strategy: str, obj: Dict[str, Any]) -> None:
    p = strategy_health_path(strategy)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def load_strategy_health(strategy: str) -> Dict[str, Any]:
    p = strategy_health_path(strategy)
    if not p.exists():
        return {"available": False, "status": "unknown"}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        obj["available"] = True
        return obj
    except Exception:
        return {"available": False, "status": "unknown"}

