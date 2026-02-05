from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def read_doctor(results_root: Path, run_id: Optional[str] = None) -> Dict[str, Any]:
    if run_id:
        run_dir = results_root / f'run_{run_id}'
    else:
        runs = [p for p in results_root.glob('run_*') if p.is_dir()]
        if not runs:
            return {}
        runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        run_dir = runs[0]
    fp = run_dir / 'doctor_report.json'
    if not fp.exists():
        return {}
    try:
        return json.loads(fp.read_text(encoding='utf-8'))
    except Exception:
        return {}


def summarize_doctor(report: Dict[str, Any]) -> str:
    if not report:
        return "No doctor_report.json found"
    checks = report.get('checks', {})
    lines = ["Doctor summary:"]
    cand = checks.get('candidates', {})
    if cand:
        lines.append(f"- candidates: missing_days={len(cand.get('missing_days', []))}, wrong_rows={len(cand.get('wrong_rows', {}))}")
    mincov = checks.get('min5_coverage', {})
    if mincov:
        pairs_total = int(mincov.get('pairs_total', 0) or 0)
        pairs_cov = int(mincov.get('pairs_covered', 0) or 0)
        rate = (pairs_cov / pairs_total) if pairs_total else 0.0
        lines.append(f"- min5 coverage: {pairs_cov}/{pairs_total} ({rate:.1%})")
    trade_cal = checks.get('trade_calendar', {})
    if trade_cal and not trade_cal.get('ok', True):
        lines.append("- trade_calendar: missing")
    cand_meta = checks.get('candidates_meta', {})
    if cand_meta:
        bad = cand_meta.get('asof_after_open', [])
        lines.append(f"- candidate_meta: asof_after_open={len(bad)}; missing_meta={len(cand_meta.get('missing_meta', []))}")
    return "\n".join(lines)

