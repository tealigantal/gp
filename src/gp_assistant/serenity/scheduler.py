from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time as datetime_time, timedelta, timezone
from statistics import quantiles
from typing import Iterable
from zoneinfo import ZoneInfo

from ..runtime.market_clock import next_trading_day_on_or_after


@dataclass(frozen=True)
class ScheduleDecision:
    cost_sec: float
    delay_sec: float
    stale_after_sec: float
    phase: str
    phase_floor_sec: float
    phase_ceiling_sec: float


def _p90(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(max(0.0, float(value)) for value in values)
    if len(ordered) < 10:
        return ordered[-1]
    return float(quantiles(ordered, n=10, method="inclusive")[8])


def _ewma(values: list[float], alpha: float) -> float:
    value = 0.0
    for item in values:
        parsed = max(0.0, float(item))
        value = parsed if value <= 0.0 else alpha * parsed + (1.0 - alpha) * value
    return value


def phase_bounds(now: datetime, *, is_trading_day: bool | None = None) -> tuple[str, float, float]:
    local = now.astimezone(ZoneInfo("Asia/Shanghai")) if now.tzinfo else now.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    trading_day = local.weekday() < 5 if is_trading_day is None else bool(is_trading_day)
    minutes = local.hour * 60 + local.minute
    if not trading_day:
        return "closed", 1800.0, 7200.0
    if 8 * 60 + 30 <= minutes < 9 * 60 + 30 or 15 * 60 <= minutes < 22 * 60 + 30:
        return "disclosure_peak", 60.0, 300.0
    if 9 * 60 + 30 <= minutes < 15 * 60:
        return "trading", 120.0, 600.0
    return "weekday_off_hours", 600.0, 3600.0


def compute_schedule(
    *,
    last_elapsed_sec: float,
    completed_durations: Iterable[float],
    now: datetime,
    alpha: float = 0.30,
    consecutive_complete_empty: int = 0,
    consecutive_failures: int = 0,
    retry_after_sec: float | None = None,
    backlog: bool = False,
    circuit_break: bool = False,
    is_trading_day: bool | None = None,
) -> ScheduleDecision:
    values = [max(0.0, float(value)) for value in completed_durations]
    last = max(0.0, float(last_elapsed_sec))
    cost = max(last, _ewma(values, alpha), _p90(values), 1.0)
    phase, floor, ceiling = phase_bounds(now, is_trading_day=is_trading_day)
    if circuit_break:
        delay = max(1800.0, floor)
    elif retry_after_sec is not None:
        delay = max(float(retry_after_sec), floor)
    elif consecutive_failures > 0:
        delay = max(floor, min(3600.0, 60.0 * (2 ** min(6, int(consecutive_failures)))))
    elif backlog:
        delay = max(15.0, min(60.0, 2.0 * cost))
    else:
        base = max(floor, min(ceiling, 4.0 * cost))
        empty_multiplier = min(4, 1 + max(0, int(consecutive_complete_empty)) // 3)
        delay = min(ceiling, base * empty_multiplier)
    observed_period = max(1.0, cost + delay)
    stale_after = max(2.0 * floor, min(3.0 * ceiling, 3.0 * observed_period))
    return ScheduleDecision(
        cost_sec=round(cost, 3),
        delay_sec=float(max(1.0, math.ceil(delay))),
        stale_after_sec=float(max(1.0, math.ceil(stale_after))),
        phase=phase,
        phase_floor_sec=floor,
        phase_ceiling_sec=ceiling,
    )


def next_due_at(now: datetime, delay_sec: float) -> str:
    return (now + timedelta(seconds=max(1.0, float(delay_sec)))).isoformat()


def trading_day_cooldown_until(now: datetime, *, trading_days: int = 10) -> str:
    """Return the start of the Nth following exchange trading day, fail-closing longer."""

    local_now = now.astimezone(ZoneInfo("Asia/Shanghai"))
    cursor = local_now.date() + timedelta(days=1)
    last_day = None
    for _ in range(max(1, int(trading_days))):
        token = next_trading_day_on_or_after(cursor)
        if token is None:
            return (now.astimezone(timezone.utc) + timedelta(days=14)).isoformat()
        last_day = datetime.strptime(token, "%Y%m%d").date()
        cursor = last_day + timedelta(days=1)
    local_boundary = datetime.combine(
        last_day,
        datetime_time.min,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
    return local_boundary.astimezone(timezone.utc).isoformat()
