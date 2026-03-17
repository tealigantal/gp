from __future__ import annotations

from typing import Any, Dict, List, Optional
from pathlib import Path
import json

from ..core.paths import results_dir


def _ls_live_shadow_dates() -> List[str]:
    base = results_dir() / "live_shadow"
    if not base.exists():
        return []
    out: List[str] = []
    for p in base.iterdir():
        if p.is_dir():
            out.append(p.name)
    out.sort()
    return out


def _read_dir_summary(path: Path) -> Dict[str, Any]:
    files = []
    sample_json: Optional[Dict[str, Any]] = None
    for p in path.iterdir():
        if p.suffix.lower() in {".json", ".csv"}:
            files.append(p.name)
            if sample_json is None and p.suffix.lower() == ".json":
                try:
                    sample_json = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    sample_json = None
    return {"files": sorted(files), "sample": sample_json}


def latest_live_shadow_summary() -> Dict[str, Any]:
    dates = _ls_live_shadow_dates()
    if not dates:
        return {"available": False, "dates": []}
    latest = dates[-1]
    base = results_dir() / "live_shadow" / latest
    return {
        "available": True,
        "dates": dates,
        "latest_date": latest,
        "summary": _read_dir_summary(base),
    }

