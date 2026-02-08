# 简介：冠军选择器。基于得分与策略兼容性为每个标的挑选“冠军”执行方案摘要。
from __future__ import annotations

from typing import Dict, Any, List


def choose_champion(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Select champion strategy for each pick given CV stats.

    Expects candidates[i]["strategies"] = {id: {cv: {...}}}
    Returns mapping symbol -> champion info.
    """
    out = {}
    for it in candidates:
        sym = it.get("symbol")
        best = None
        best_score = -1e9
        for sid, meta in (it.get("strategies") or {}).items():
            cv = (meta.get("cv") or {})
            wr = float(cv.get("win_rate_5d_mean", 0.0))
            mr = float(cv.get("mean_return_5d_mean", 0.0))
            dd = float(cv.get("drawdown_proxy_mean", 0.0))
            score = 0.7 * wr + 0.2 * max(0.0, mr) - 0.1 * abs(dd)
            if score > best_score:
                best_score = score
                best = {"strategy": sid, "cv": cv, "score": score}
        if best is None:
            best = {"strategy": "NA", "cv": {}, "score": 0.0}
        out[sym] = best
    return out
