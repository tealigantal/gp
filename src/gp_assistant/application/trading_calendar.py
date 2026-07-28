from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

import pandas as pd

from ..contracts.market import TradingCalendarRef


@dataclass(frozen=True)
class CnATradingCalendar:
    open_days: frozenset[date]
    ref: TradingCalendarRef

    def is_open(self, value: date) -> bool:
        self._require_covered(value)
        return value in self.open_days

    @property
    def first_open_day(self) -> date:
        return min(self.open_days)

    @property
    def last_open_day(self) -> date:
        return max(self.open_days)

    def _require_covered(self, value: date) -> None:
        if value < self.first_open_day or value > self.last_open_day:
            raise ValueError("trading_calendar_out_of_range")

    def next_open_after(self, value: date) -> date:
        if value >= self.last_open_day:
            raise ValueError("trading_calendar_out_of_range")
        cursor = value + timedelta(days=1)
        while cursor <= self.last_open_day and cursor not in self.open_days:
            cursor += timedelta(days=1)
        if cursor > self.last_open_day:
            raise ValueError("trading_calendar_out_of_range")
        return cursor

    def previous_open_before(self, value: date) -> date:
        if value <= self.first_open_day:
            raise ValueError("trading_calendar_out_of_range")
        cursor = value - timedelta(days=1)
        while cursor >= self.first_open_day and cursor not in self.open_days:
            cursor -= timedelta(days=1)
        if cursor < self.first_open_day:
            raise ValueError("trading_calendar_out_of_range")
        return cursor

    def previous_open_on_or_before(self, value: date) -> date:
        if value < self.first_open_day:
            raise ValueError("trading_calendar_out_of_range")
        if value in self.open_days:
            return value
        return self.previous_open_before(value + timedelta(days=1))

    def open_days_between(self, start: date, end: date) -> tuple[date, ...]:
        if end < start:
            return ()
        self._require_covered(start)
        self._require_covered(end)
        return tuple(day for day in sorted(self.open_days) if start <= day <= end)


@lru_cache(maxsize=1)
def load_cn_a_calendar() -> CnATradingCalendar:
    path = Path("data/raw/trade_calendar.parquet")
    if not path.exists():
        raise ValueError("trading_calendar_unavailable")
    frame = pd.read_parquet(path, columns=["cal_date", "is_open"])
    open_days = frozenset(
        pd.to_datetime(frame.loc[frame["is_open"].astype(int) == 1, "cal_date"].astype(str), format="%Y%m%d").dt.date
    )
    if not open_days:
        raise ValueError("trading_calendar_empty")
    digest = sha256(path.read_bytes()).hexdigest()
    return CnATradingCalendar(
        open_days=open_days,
        ref=TradingCalendarRef(
            calendar_id="cn_a_trade_calendar",
            revision=digest[:16],
            source="data/raw/trade_calendar.parquet",
        ),
    )
