from __future__ import annotations

"""
Deprecated thin wrappers kept for backward imports.

This module now delegates to recommend.trading_clock which provides
the unified trading-time semantics based on trading_date + market_phase.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from .trading_clock import (
    detect_cutoff_for_now as _detect_cutoff_for_now,
    is_run_valid_for_operation as _is_run_valid_for_operation,
)


def detect_cutoff(now: Optional[datetime] = None) -> str:
    return _detect_cutoff_for_now(now)


def is_artifact_valid(artifact: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    # Interpret as validity for recommendation reuse (not follow-up)
    return _is_run_valid_for_operation(artifact, now, operation="recommend")
