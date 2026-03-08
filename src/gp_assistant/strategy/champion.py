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
    # Freshness thresholds and penalties (centralized here)
    SETUP_AGE_FRESH_MAX = 5      # bars
    SETUP_AGE_STALE_BARS = 10    # bars
    SETUP_AGE_PENALTY_PER_BAR = 0.03
    SETUP_COUNT_LOW = 3
    SETUP_COUNT_PENALTY = 0.3

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

            # Setup freshness penalty (strong constraint)
            setup = meta.get("setup") or {}
            setup_age = int(setup.get("age", 999)) if isinstance(setup, dict) else 999
            setup_count = int(setup.get("count", 0)) if isinstance(setup, dict) else 0
            freshness_state = "missing"
            if setup_age == 999 and not setup:
                freshness_state = "missing"
            elif setup_age <= SETUP_AGE_FRESH_MAX:
                freshness_state = "fresh"
            elif setup_age <= SETUP_AGE_STALE_BARS:
                freshness_state = "aging"
            else:
                freshness_state = "stale"

            setup_pen_age = 0.0
            if setup_age > SETUP_AGE_FRESH_MAX:
                setup_pen_age = -min(1.5, (setup_age - SETUP_AGE_FRESH_MAX) * SETUP_AGE_PENALTY_PER_BAR)
                if freshness_state in {"aging", "stale"}:
                    reasons.append("stale_setup")
            setup_pen_cnt = 0.0
            if setup_count < SETUP_COUNT_LOW:
                setup_pen_cnt = -SETUP_COUNT_PENALTY
                reasons.append("low_setup_count")
            setup_penalty = setup_pen_age + setup_pen_cnt

            # Final score
            event_component = (
                0.50 * wr5 + 0.20 * wr10 + 0.15 * max(0.0, mr5) + 0.05 * max(0.0, mr10)
            )
            cv_component = 0.10 * cv_wr + 0.05 * max(0.0, cv_mr) - 0.05 * abs(cv_dd)
            meta_penalty = pen + sample_boost
            score = event_component + cv_component + meta_penalty + setup_penalty
            if score > best_score:
                best_score = score
                best = {
                    "strategy": sid,
                    "cv": cv,
                    "event": ev,
                    "score": float(score),
                    "meta_penalty": float(meta_penalty),
                    "setup_penalty": float(setup_penalty),
                    "freshness_state": freshness_state,
                    "reasons": reasons,
                    "score_breakdown": {
                        "event_component": float(event_component),
                        "cv_component": float(cv_component),
                        "meta_penalty": float(meta_penalty),
                        "setup_penalty": float(setup_penalty),
                        "total": float(score),
                    },
                }
        if best is None:
            best = {"strategy": "NA", "cv": {}, "event": {}, "score": 0.0, "reasons": ["no_strategies"], "setup_penalty": -0.5, "freshness_state": "missing", "score_breakdown": {"event_component": 0.0, "cv_component": 0.0, "meta_penalty": 0.0, "setup_penalty": -0.5, "total": -0.5}}
        out[sym] = best
    return out
