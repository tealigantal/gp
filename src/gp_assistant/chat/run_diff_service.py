from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..kernel.facade import get_gated_artifact_v2


def _symbols_from_art(art: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for it in (art.get("items") or []) if isinstance(art, dict) else []:
        try:
            s = str(it.get("symbol") or "")
            if s:
                out.append(s)
        except Exception:
            continue
    return out


def diff_runs(current_run_id: Optional[str], previous_run_id: Optional[str]) -> Dict[str, Any]:
    if not current_run_id or not previous_run_id:
        return {
            "ok": True,
            "summary_reason": "no_previous_run",
            "added_symbols": [],
            "removed_symbols": [],
            "rank_changes": [],
            "tradeable_change": None,
            "run_gating_change": None,
        }
    cur = get_gated_artifact_v2(run_id=current_run_id)
    prev = get_gated_artifact_v2(run_id=previous_run_id)
    cur_syms = _symbols_from_art(cur)
    prev_syms = _symbols_from_art(prev)
    added = [s for s in cur_syms if s not in prev_syms]
    removed = [s for s in prev_syms if s not in cur_syms]
    # rank changes: list of tuples (symbol, prev_rank, cur_rank)
    rank_changes: List[Dict[str, Any]] = []
    for s in cur_syms:
        if s in prev_syms:
            rank_changes.append({"symbol": s, "prev": prev_syms.index(s) + 1, "cur": cur_syms.index(s) + 1})
    tradeable_change = None
    try:
        if cur.get("tradeable") != prev.get("tradeable"):
            tradeable_change = {"from": prev.get("tradeable"), "to": cur.get("tradeable")}
    except Exception:
        pass
    run_gating_change = None
    try:
        crg = (cur.get("run_gating") or {}).get("decision")
        prg = (prev.get("run_gating") or {}).get("decision")
        if crg != prg:
            run_gating_change = {"from": prg, "to": crg}
    except Exception:
        pass
    reason = "run_changed" if (added or removed or (tradeable_change is not None) or (run_gating_change is not None)) else "no_material_change"
    return {
        "ok": True,
        "summary_reason": reason,
        "added_symbols": added,
        "removed_symbols": removed,
        "rank_changes": rank_changes,
        "tradeable_change": tradeable_change,
        "run_gating_change": run_gating_change,
    }

