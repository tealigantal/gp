# 简介：冠军选择器。基于得分与策略兼容性为每个标的挑选“冠军”执行方案摘要。
from __future__ import annotations

from typing import Dict, Any, List
from . import library as strat_lib


def choose_champion(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Select champion strategy for each symbol using per-strategy metrics.

    Inputs per candidate:
      - strategies: {sid: {cv: CVStats-like dict, event: EventStats-like dict, setup?: {...}}}
    Scoring combines:
      - strategy event stats (primary discriminator per-strategy)
      - generic CV (symbol-level) as a weak regularizer
      - strategy metadata (eligibility, penalties)
    """
    out: Dict[str, Any] = {}
    meta_map = getattr(strat_lib, "METADATA", {}) or {}

    for it in candidates:
        sym = it.get("symbol")
        best: Dict[str, Any] | None = None
        best_score = -1e9
        for sid, meta in (it.get("strategies") or {}).items():
            cv = (meta.get("cv") or {})
            ev = (meta.get("event") or {})
            st_meta = meta_map.get(str(sid), {})

            # Base from per-strategy event stats
            wr5 = float(ev.get("win_rate_5", ev.get("win_rate_5d", 0.0) or ev.get("win_rate_5d_mean", 0.0)))
            wr10 = float(ev.get("win_rate_10", 0.0))
            mr5 = float(ev.get("mean_return_5", 0.0))
            mr10 = float(ev.get("mean_return_10", 0.0))
            mdd = float(ev.get("mdd10_proxy", 0.0))
            k = int(ev.get("k", 0))

            # Fallback to CV regularizer
            cv_wr = float(cv.get("win_rate_5d_mean", 0.0))
            cv_mr = float(cv.get("mean_return_5d_mean", 0.0))
            cv_dd = float(cv.get("drawdown_proxy_mean", 0.0))

            # Eligibility penalties
            pen = 0.0
            reasons: List[str] = []
            if not bool(st_meta.get("live_enabled", True)):
                pen -= 0.5; reasons.append("not_live_enabled")
            if not bool(st_meta.get("champion_eligible", True)):
                pen -= 0.8; reasons.append("not_champion_eligible")
            if str(st_meta.get("direction", "long")) != "long":
                pen -= 0.3; reasons.append("non_long_direction")
            if bool(st_meta.get("prefer_observation_only", False)):
                pen -= 0.2; reasons.append("prefer_observe")

            # Sample size dampening
            sample_boost = 0.0 if k >= 10 else -0.2

            # Final score
            score = (
                0.50 * wr5 + 0.20 * wr10 + 0.15 * max(0.0, mr5) + 0.05 * max(0.0, mr10)
                - 0.10 * abs(mdd)
                + 0.10 * cv_wr + 0.05 * max(0.0, cv_mr) - 0.05 * abs(cv_dd)
                + pen + sample_boost
            )
            if score > best_score:
                best_score = score
                best = {
                    "strategy": sid,
                    "cv": cv,
                    "event": ev,
                    "score": float(score),
                    "meta_penalty": pen,
                    "reasons": reasons,
                }
        if best is None:
            best = {"strategy": "NA", "cv": {}, "event": {}, "score": 0.0, "reasons": ["no_strategies"]}
        out[sym] = best
    return out
