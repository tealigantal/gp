# src/gp_assistant/recommend/modes/dev.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...dev.fixtures import dev_recommend_payload


def run(
    date: Optional[str] = None,
    topk: int = 3,
    universe: str = "auto",
    symbols: Optional[List[str]] = None,
    risk_profile: str = "normal",
) -> Dict[str, Any]:
    return dev_recommend_payload(date=date, topk=topk, universe=universe, symbols=symbols, risk_profile=risk_profile)