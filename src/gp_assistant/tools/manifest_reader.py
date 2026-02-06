from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def read_manifest(results_root: Path, run_id: Optional[str] = None) -> Dict[str, Any]:
    if run_id:
        run_dir = results_root / f'run_{run_id}'
    else:
        runs = [p for p in results_root.glob('run_*') if p.is_dir()]
        if not runs:
            return {}
        runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        run_dir = runs[0]
    fp = run_dir / 'manifest.json'
    if not fp.exists():
        return {}
    try:
        return json.loads(fp.read_text(encoding='utf-8'))
    except Exception:
        return {}

def summarize_manifest(m: Dict[str, Any]) -> str:
    if not m:
        return "No manifest.json found"
    ep = m.get('engine_policy', {})
    cm = m.get('cost_model', {})
    ap = m.get('asof_policy', {})
    lines = [
        f"git={m.get('git_commit','unknown')} cfg_hash={m.get('configs_hash','-')[:8]}",
        f"engine: t+1={ep.get('t_plus_one',True)} lot={ep.get('lot_size',100)} next_open={ep.get('next_open_fill',True)}",
        f"cost: slippage_bps={cm.get('slippage_bps',0)} commission={cm.get('commission_rate',0)} stamp_duty={cm.get('stamp_duty_rate',0)}",
        f"asof: rule={ap.get('asof_datetime_rule','D-1 close')} pool_size={ap.get('pool_size','?')}",
    ]
    return "\n".join(lines)

