from __future__ import annotations

from pathlib import Path
from typing import List


def list_runs(results_root: Path, limit: int = 10) -> List[str]:
    runs = [p for p in results_root.glob('run_*') if p.is_dir()]
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: List[str] = []
    for p in runs[:limit]:
        out.append(p.name)
    return out

