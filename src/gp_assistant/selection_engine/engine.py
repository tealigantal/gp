from __future__ import annotations

"""
Unified recommendation engine entrypoint.

This module exposes a single run(...) that both the default agent and
service pipeline can call to generate recommendations. Internally it
delegates to the canonical implementation in agent.run to avoid
duplicating logic.
"""

from typing import Any, Dict, List, Optional


def run(
    *,
    date: Optional[str] = None,
    topk: int = 3,
    universe: str = "auto",
    symbols: Optional[List[str]] = None,
    risk_profile: str = "normal",
) -> Dict[str, Any]:
    # Lazy import to avoid circulars
    from .agent import run as _agent_run  # noqa: WPS433

    return _agent_run(date=date, topk=topk, universe=universe, symbols=symbols, risk_profile=risk_profile)

