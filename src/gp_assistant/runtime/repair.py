from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from .market_clock import compute_market_state


class RepairStatusSnapshot(BaseModel):
    repair_status: str = "idle"
    repair_stage: str = "idle"
    market_phase: Optional[str] = None
    daily_target_day: Optional[str] = None
    pulse_target_trade_day: Optional[str] = None
    pulse_target_slot_at: Optional[str] = None
    last_repair_started_at: Optional[str] = None
    last_repair_finished_at: Optional[str] = None
    blocking_reason: Optional[str] = None
    artifact_status: Optional[str] = None


def _repair_status_path() -> Path:
    return Path("store") / "runtime" / "repair_status.json"


def _default_snapshot() -> RepairStatusSnapshot:
    state = compute_market_state()
    return RepairStatusSnapshot(
        repair_status="idle",
        repair_stage="idle",
        market_phase=state.market_phase,
        daily_target_day=state.target_daybook_effective_day,
        pulse_target_trade_day=state.target_pulse_trade_day,
        pulse_target_slot_at=state.target_pulse_slot_at,
        artifact_status=state.data_status,
    )


def load_repair_status_snapshot() -> RepairStatusSnapshot | None:
    path = _repair_status_path()
    if not path.exists():
        return _default_snapshot()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_snapshot()
    if not isinstance(payload, dict):
        return _default_snapshot()
    base = _default_snapshot().model_dump()
    base.update(payload)
    try:
        return RepairStatusSnapshot.model_validate(base)
    except Exception:
        return _default_snapshot()
