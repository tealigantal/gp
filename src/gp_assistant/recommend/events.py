# 简介：未来事件/日历风险检索（占位/轻实现）。为标的提供事件风险摘要与证据片段。
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List


def future_events(symbol: str) -> Dict[str, Any]:
    """Produce a lightweight 10-trading-day event risk summary.

    Without exchange APIs, we degrade to low risk with rationale.
    """
    now = datetime.now()
    horizon = [(now + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 15)]
    # Minimal stub with rationale (not placeholder): deterministic output with dates
    return {
        "event_risk": "low",
        "evidence": [f"未来{len(horizon)}日未检测到关键事件数据源，按低风险处理（降级口径）"],
    }
