from __future__ import annotations

"""
Phase 5: Validation automation runner (minimal, deterministic, no side effects on import).

Responsibilities:
- Provide a unified function to refresh validation-related outputs
- Build a consolidated validation summary and persist to store/validation/latest_summary.json

This module uses only stdlib and existing lightweight helpers. It does not fetch
network data and remains safe to import in containers.
"""

from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime, timezone
import json

from ..core.paths import store_dir
from .event_stats import load_event_stats, save_event_stats
from .walkforward_stats import load_walkforward, save_walkforward
from .paper_trade import load_paperfolio
from .strategy_health import compute_strategy_health, load_strategy_health, save_strategy_health


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validation_root() -> Path:
    p = store_dir() / "validation"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _list_strategies_from_store() -> List[str]:
    root = _validation_root()
    cands: List[str] = []
    for sub in ("event_stats", "walkforward", "strategy_health"):
        d = root / sub
        if not d.exists():
            continue
        for f in d.glob("*.json"):
            name = f.stem
            if name:
                cands.append(name)
    # Unique, deterministic order
    return sorted({*cands})


def update_event_stats(strategies: Optional[List[str]] = None) -> Tuple[bool, List[str]]:
    """No-op consolidator for event stats.

    In Phase 5 we do not recompute from raw market data. We ensure the file shape
    is present by re-saving existing stats when available.
    """
    ok = True
    errors: List[str] = []
    for s in (strategies or _list_strategies_from_store()):
        try:
            st = load_event_stats(s)
            if st:
                save_event_stats(s, st)
        except Exception as e:  # noqa: BLE001
            ok = False
            errors.append(f"event_stats:{s}:{type(e).__name__}")
    return ok, errors


def update_walkforward_stats(strategies: Optional[List[str]] = None) -> Tuple[bool, List[str]]:
    ok = True
    errors: List[str] = []
    for s in (strategies or _list_strategies_from_store()):
        try:
            wf = load_walkforward(s)
            if wf:
                save_walkforward(s, wf)
        except Exception as e:  # noqa: BLE001
            ok = False
            errors.append(f"walkforward:{s}:{type(e).__name__}")
    return ok, errors


def update_strategy_health(strategies: Optional[List[str]] = None) -> Tuple[bool, List[str]]:
    ok = True
    errors: List[str] = []
    for s in (strategies or _list_strategies_from_store()):
        try:
            h = compute_strategy_health(s)
            save_strategy_health(s, h)
        except Exception as e:  # noqa: BLE001
            ok = False
            errors.append(f"strategy_health:{s}:{type(e).__name__}")
    return ok, errors


def build_validation_summary(strategies: Optional[List[str]] = None) -> Dict[str, Any]:
    """Construct a consolidated validation summary object (does not write)."""
    strategies = strategies or _list_strategies_from_store()
    event_obj: Dict[str, Any] = {}
    wf_obj: Dict[str, Any] = {}
    health_obj: Dict[str, Any] = {}
    for s in strategies:
        try:
            event_obj[s] = load_event_stats(s)
        except Exception:
            event_obj[s] = {"available": False}
        try:
            wf_obj[s] = load_walkforward(s)
        except Exception:
            wf_obj[s] = {"available": False}
        try:
            health_obj[s] = load_strategy_health(s)
        except Exception:
            health_obj[s] = {"available": False}
    try:
        paperfolio = load_paperfolio()
    except Exception:
        paperfolio = {"available": False, "picks": []}
    try:
        live_shadow = latest_live_shadow_summary()
    except Exception:
        live_shadow = {"available": False, "dates": []}
    return {
        "as_of": _utc_now_iso(),
        "parts": {
            "event_stats": event_obj,
            "walkforward": wf_obj,
            "strategy_health": health_obj,
            "paper_trade": paperfolio,
            "live_shadow": live_shadow,
        },
        "source": {
            "validation_root": str(_validation_root()),
        },
    }


def persist_validation_summary(obj: Dict[str, Any]) -> Path:
    p = _validation_root() / "latest_summary.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def run_validation_refresh(strategies: Optional[List[str]] = None) -> Dict[str, Any]:
    """Unified entry: refresh validation artifacts and persist consolidated summary.

    Returns a structured status object (no exceptions for partial failures).
    """
    started = _utc_now_iso()
    updated: List[str] = []
    failed: List[str] = []
    warnings: List[str] = []

    # 1) Update components (best-effort)
    ok1, e1 = update_event_stats(strategies)
    (updated if ok1 else failed).append("event_stats")
    warnings.extend(e1)
    ok2, e2 = update_walkforward_stats(strategies)
    (updated if ok2 else failed).append("walkforward")
    warnings.extend(e2)
    ok3, e3 = update_strategy_health(strategies)
    (updated if ok3 else failed).append("strategy_health")
    warnings.extend(e3)

    # 2) Build summary and persist
    summary = build_validation_summary(strategies)
    path = persist_validation_summary(summary)

    finished = _utc_now_iso()
    ok_all = (not failed)
    return {
        "ok": ok_all,
        "started_at": started,
        "finished_at": finished,
        "updated_parts": updated,
        "failed_parts": failed,
        "warnings": warnings,
        "summary_path": str(path),
    }

