from __future__ import annotations

from typing import Any, Dict, List, Optional
import json
from pathlib import Path
from datetime import datetime, timezone

from ..core.paths import store_dir


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def paper_trade_path() -> Path:
    base = store_dir() / "validation" / "paper_trade"
    base.mkdir(parents=True, exist_ok=True)
    return base / "current.json"


def _load_current() -> Dict[str, Any]:
    p = paper_trade_path()
    if not p.exists():
        return {"picks": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"picks": []}


def _save_current(obj: Dict[str, Any]) -> None:
    p = paper_trade_path()
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def start_tracking(pick_id: str, symbol: str, strategy: Optional[str], as_of: str, price_ref: Optional[float]) -> None:
    cur = _load_current()
    if not any(x.get("pick_id") == pick_id for x in cur.get("picks", [])):
        cur.setdefault("picks", []).append({
            "pick_id": pick_id,
            "symbol": symbol,
            "strategy": strategy,
            "as_of": as_of,
            "price_ref": price_ref,
            "entry_reached": False,
            "hit_stop": False,
            "hit_take": False,
            "mfe": 0.0,
            "mae": 0.0,
            "holding_days": 0,
            "final_state": None,
            "updated_at": _now_utc_iso(),
        })
        _save_current(cur)


def update_with_bars(symbol: str, bars: List[Dict[str, Any]], entry_zone: Optional[List[float]] = None, stop: Optional[float] = None, takes: Optional[List[float]] = None) -> None:
    cur = _load_current()
    for p in cur.get("picks", []):
        if str(p.get("symbol")) != str(symbol):
            continue
        closes = [float(b.get("close")) for b in bars if b.get("close") is not None]
        if not closes:
            continue
        ref = float(p.get("price_ref") or closes[0])
        p["mfe"] = max(p.get("mfe", 0.0), max(c - ref for c in closes))
        p["mae"] = min(p.get("mae", 0.0), min(c - ref for c in closes))
        p["holding_days"] = int(p.get("holding_days") or 0) + 1
        # entry check
        if entry_zone and not p.get("entry_reached"):
            lo, hi = float(entry_zone[0]), float(entry_zone[1])
            if any((lo <= c <= hi) for c in closes):
                p["entry_reached"] = True
        # stop/take checks
        if stop and not p.get("hit_stop"):
            if any(c <= float(stop) for c in closes):
                p["hit_stop"] = True
                p["final_state"] = p.get("final_state") or "stopped"
        if takes and not p.get("hit_take"):
            if any(c >= float(max(takes)) for c in closes):
                p["hit_take"] = True
                p["final_state"] = p.get("final_state") or "target_hit"
        p["updated_at"] = _now_utc_iso()
    _save_current(cur)


def load_paperfolio() -> Dict[str, Any]:
    cur = _load_current()
    cur.setdefault("available", True)
    return cur

