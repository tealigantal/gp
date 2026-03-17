from __future__ import annotations

from typing import Any, Dict, List
from pathlib import Path
import json

from ..core.paths import store_dir
from .contracts import empty_portfolio_state


def _portfolio_root() -> Path:
    p = store_dir() / "portfolio"
    p.mkdir(parents=True, exist_ok=True)
    return p


def portfolio_state_path() -> Path:
    return _portfolio_root() / "latest.json"


def events_log_path() -> Path:
    return _portfolio_root() / "events.jsonl"


def read_portfolio_state() -> Dict[str, Any]:
    p = portfolio_state_path()
    if not p.exists():
        return empty_portfolio_state()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return empty_portfolio_state()


def save_portfolio_state(state: Dict[str, Any]) -> None:
    p = portfolio_state_path()
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def append_events(events: List[Dict[str, Any]]) -> None:
    if not events:
        return
    p = events_log_path()
    with p.open("a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def read_recent_events(limit: int = 100) -> List[Dict[str, Any]]:
    p = events_log_path()
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()[-limit:]
    out: List[Dict[str, Any]] = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out

