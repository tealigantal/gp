from __future__ import annotations

"""One explicit market-time contract for the recommendation runtime.

The old runtime used ``as_of``/``trade_day`` for both the day a plan targets
and the most recent daily bar that is allowed to influence it.  This mapping
keeps compatibility aliases at the boundary while core code uses named fields.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any


def ymd(value: str | None) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else None


def iso_day(value: str | None) -> str | None:
    digits = ymd(value)
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}" if digits else None


MARKET_TIME_SNAPSHOT_FIELDS = (
    "decision_trade_day",
    "daybook_effective_day",
    "pulse_trade_day",
    "pulse_slot_closed_at",
    "market_phase",
    "target_mode",
    "pending_eod_day",
    "calendar_blocking_reason",
)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def market_time_binding(value: Any) -> dict[str, str]:
    return {
        name: str(_field(value, name) or "")
        for name in MARKET_TIME_SNAPSHOT_FIELDS
    }


def compare_snapshot_market_time(snapshot: Any, current: Any) -> dict[str, Any]:
    current_binding = market_time_binding(current)
    snapshot_binding = market_time_binding(snapshot)
    mismatches = [
        name
        for name in MARKET_TIME_SNAPSHOT_FIELDS
        if current_binding[name] != snapshot_binding[name]
    ]
    revision = sha256(
        json.dumps(
            current_binding,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "matches": not mismatches,
        "mismatches": mismatches,
        "revision": revision,
        "current": current_binding,
        "expected": snapshot_binding,
        "reason": None,
    }


@dataclass(frozen=True)
class MarketTimeContext(Mapping[str, Any]):
    """Named dates for one market observation and recommendation decision."""

    decision_trade_day: str
    daybook_effective_day: str
    pulse_trade_day: str | None
    pulse_slot_closed_at: str | None
    observed_at: str
    market_phase: str
    target_mode: str
    pending_eod_day: str | None = None
    eod_probe: dict[str, Any] | None = None
    calendar_status: str = "unknown"
    calendar_source: str = ""
    calendar_range: dict[str, Any] | None = None
    calendar_error: str | None = None
    next_trading_day: str | None = None
    calendar_blocking_reason: str | None = None

    @property
    def decision_trade_ymd(self) -> str:
        return ymd(self.decision_trade_day) or ""

    @property
    def daybook_effective_ymd(self) -> str:
        return ymd(self.daybook_effective_day) or ""

    def as_dict(self) -> dict[str, Any]:
        # Legacy keys are deliberately aliases for callers still crossing the
        # old contract; new core code must use the named attributes above.
        return {
            "decision_trade_day": self.decision_trade_day,
            "daybook_effective_day": self.daybook_effective_day,
            "pulse_trade_day": self.pulse_trade_day,
            "pulse_slot_closed_at": self.pulse_slot_closed_at,
            "observed_at": self.observed_at,
            "market_phase": self.market_phase,
            "target_mode": self.target_mode,
            "pending_eod_day": self.pending_eod_day,
            "eod_probe": self.eod_probe,
            "calendar_status": self.calendar_status,
            "calendar_source": self.calendar_source,
            "calendar_range": self.calendar_range or {},
            "calendar_error": self.calendar_error,
            "next_trading_day": self.next_trading_day,
            "calendar_blocking_reason": self.calendar_blocking_reason,
            "target_ymd": self.daybook_effective_ymd,
            "target_day": self.daybook_effective_day,
            "daybook_trading_day": self.decision_trade_ymd,
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_dict())

    def __len__(self) -> int:
        return len(self.as_dict())
