# 简介：打分逻辑。综合环境、主题、指标面板、事件/公告等要素计算候选得分，
# 驱动 picks 排序与截断。
from __future__ import annotations

from typing import Dict, Any


def score_item(item: Dict[str, Any]) -> float:
    """Compute 0-100 score without overriding veto flags.

    Weights:
    - env 0–20
    - theme 0–15
    - trend 0–20
    - volatility 0–15
    - chip 0–15
    - statistics 0–10
    - announcements/events 0–5
    - relative strength 0–10
    """
    env = item.get("_env", {})
    env_grade = env.get("grade", "C")
    env_map = {"A": 20, "B": 14, "C": 8, "D": 2}
    s_env = env_map.get(env_grade, 8)

    theme = item.get("_theme_strength", 0.0)
    s_theme = max(0.0, min(15.0, 15.0 * float(theme)))

    inds = item.get("indicators", {})
    slope20 = float(inds.get("slope20", 0.0) or 0.0)
    close = float(item.get("close", 0.0) or 0.0)
    ma20 = float(inds.get("ma20", 0.0) or 0.0)
    trend = 0.0
    if ma20 > 0:
        trend = max(0.0, min(1.0, 0.5 * slope20 + 0.5 * (close - ma20) / ma20))
    s_trend = 20.0 * trend

    atrp = float(inds.get("atr_pct", 0.0) or 0.0)
    gap = float(inds.get("gap_pct", 0.0) or 0.0)
    dist_high = float(item.get("chip", {}).get("dist_to_90_high_pct", 0.0) or 0.0)
    s_vol = max(0.0, 15.0 - 100.0 * (atrp * 0.5 + max(0.0, gap) * 0.5 + max(0.0, dist_high) * 0.5))

    chip = item.get("chip", {})
    prof = float(chip.get("profit_ratio", 0.5))
    conc = float(chip.get("concentration_90", 0.5))
    s_chip = 15.0 * (0.6 * prof + 0.4 * (1.0 - abs(conc - 0.8)))

    stats = item.get("stats", {})
    wr5 = float(stats.get("win_rate_5", 0.5))
    m5 = float(stats.get("avg_return_5", 0.0))
    k = int(stats.get("k", 0))
    pen = 0.2 if k < 5 else 0.0
    s_stat = max(0.0, 10.0 * (0.7 * wr5 + 0.3 * max(0.0, m5)) - pen * 10.0)

    ann = item.get("announcement_risk", {}).get("risk_level", "low")
    ev = item.get("event_risk", {}).get("event_risk", "low")
    s_risk = 5.0
    if ann == "high":
        s_risk -= 2.5
    if ev == "high":
        s_risk -= 2.5

    # Relative strength contribution
    rs = item.get("rel_strength", {})
    rs5 = float(rs.get("rs5", 0.0) or 0.0)
    rs20 = float(rs.get("rs20", 0.0) or 0.0)
    # Scale: 100*(0.6*rs5+0.4*rs20), clamp 0..10
    s_rs = max(0.0, min(10.0, 100.0 * (0.6 * max(0.0, rs5) + 0.4 * max(0.0, rs20))))

    total = s_env + s_theme + s_trend + s_vol + s_chip + s_stat + s_risk + s_rs
    return float(max(0.0, min(100.0, total)))
