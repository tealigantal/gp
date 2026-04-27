from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional

import pandas as pd
import zoneinfo

from ..core.config import load_config

try:  # optional calendar loader
    from ..selection_engine.modes.service import _load_trade_calendar  # type: ignore
except Exception:  # pragma: no cover
    _load_trade_calendar = None  # type: ignore


PHASE_NON_TRADING = "NON_TRADING"
PHASE_PREOPEN = "PREOPEN"
PHASE_OPEN_NO_FIRST_BAR = "OPEN_NO_FIRST_BAR"
PHASE_INTRADAY_AM = "INTRADAY_AM"
PHASE_LUNCH_BREAK = "LUNCH_BREAK"
PHASE_INTRADAY_PM = "INTRADAY_PM"
PHASE_CLOSING_AUCTION = "CLOSING_AUCTION"
PHASE_POSTCLOSE_PENDING = "POSTCLOSE_PENDING"
PHASE_POSTCLOSE_READY = "POSTCLOSE_READY"

AM_SLOT_CLOSE_START = time(9, 35)
AM_SLOT_CLOSE_END = time(11, 30)
PM_SLOT_CLOSE_START = time(13, 5)
PM_SLOT_CLOSE_END = time(14, 55)


@dataclass
class MarketState:
    market_phase: str
    calendar_source: str
    is_trading_day: bool
    target_daybook_effective_day: str
    target_pulse_trade_day: Optional[str]
    target_pulse_slot_at: Optional[str]
    data_status: str


def _tz_now(now: Optional[datetime]) -> datetime:
    cfg = load_config()
    tz = zoneinfo.ZoneInfo(getattr(cfg, "timezone", "Asia/Shanghai"))
    current = now or datetime.now(tz=tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    return current.astimezone(tz)


def _load_calendar_df():
    try:
        return _load_trade_calendar() if _load_trade_calendar else None
    except Exception:  # pragma: no cover
        return None


def _is_open_day(d: pd.Timestamp, cal_df) -> bool:
    if isinstance(cal_df, pd.DataFrame) and not cal_df.empty and {"cal_date", "is_open"} <= set(cal_df.columns):
        ymd = d.strftime("%Y%m%d")
        row = cal_df[cal_df["cal_date"] == ymd]
        if not row.empty:
            try:
                return int(row.iloc[0]["is_open"]) == 1
            except Exception:
                pass
    return d.weekday() < 5


def _last_open_day_on_or_before(d: pd.Timestamp, cal_df) -> pd.Timestamp:
    if isinstance(cal_df, pd.DataFrame) and not cal_df.empty and {"cal_date", "is_open"} <= set(cal_df.columns):
        ymd = d.strftime("%Y%m%d")
        sub = cal_df[(cal_df["cal_date"] <= ymd) & (cal_df["is_open"] == 1)]
        if not sub.empty:
            try:
                return pd.to_datetime(str(sub.iloc[-1]["cal_date"])).normalize()
            except Exception:
                pass
    dd = d
    while dd.weekday() >= 5:
        dd = dd - pd.Timedelta(days=1)
    return dd.normalize()


def _trade_day_for_now(tnow: datetime, cal_df) -> str:
    today = pd.Timestamp(tnow.date())
    if _is_open_day(today, cal_df):
        return today.strftime("%Y%m%d")
    return _last_open_day_on_or_before(today, cal_df).strftime("%Y%m%d")


def _date_from_trade_day(trade_day: str) -> date:
    return datetime.strptime(trade_day, "%Y%m%d").date()


def _combine(trade_day: str, hh: int, mm: int) -> datetime:
    return datetime.combine(_date_from_trade_day(trade_day), time(hh, mm))


def format_slot_at(slot_dt: datetime | None) -> Optional[str]:
    if slot_dt is None:
        return None
    return slot_dt.strftime("%Y-%m-%d %H:%M:%S")


def slot_id_for(slot_at: datetime | str | None) -> Optional[str]:
    if slot_at is None:
        return None
    dt = pd.to_datetime(slot_at).to_pydatetime() if not isinstance(slot_at, datetime) else slot_at
    return dt.strftime("%Y%m%d_%H%M")


def iter_trade_slots(trade_day: str, *, up_to: datetime | str | None = None) -> list[datetime]:
    slots: list[datetime] = []
    cur = _combine(trade_day, 9, 35)
    am_end = _combine(trade_day, 11, 30)
    while cur <= am_end:
        slots.append(cur)
        cur += timedelta(minutes=5)
    cur = _combine(trade_day, 13, 5)
    pm_end = _combine(trade_day, 14, 55)
    while cur <= pm_end:
        slots.append(cur)
        cur += timedelta(minutes=5)
    if up_to is None:
        return slots
    cutoff = pd.to_datetime(up_to).to_pydatetime() if not isinstance(up_to, datetime) else up_to
    return [slot for slot in slots if slot <= cutoff]


def next_trade_slot(trade_day: str, slot_at: datetime | str | None) -> Optional[datetime]:
    slots = iter_trade_slots(trade_day)
    if slot_at is None:
        return slots[0] if slots else None
    current = pd.to_datetime(slot_at).to_pydatetime() if not isinstance(slot_at, datetime) else slot_at
    for slot in slots:
        if slot > current:
            return slot
    return None


def last_closed_trade_slot(now: Optional[datetime] = None) -> Optional[datetime]:
    tnow = _tz_now(now)
    trade_day = _trade_day_for_now(tnow, _load_calendar_df())
    tt = tnow.time()
    if tt < AM_SLOT_CLOSE_START:
        return None
    if AM_SLOT_CLOSE_START <= tt <= AM_SLOT_CLOSE_END:
        minute = (tt.minute // 5) * 5
        floored = tnow.replace(minute=minute, second=0, microsecond=0)
        return floored if floored.time() >= AM_SLOT_CLOSE_START else None
    if AM_SLOT_CLOSE_END < tt < PM_SLOT_CLOSE_START:
        return _combine(trade_day, 11, 30)
    if PM_SLOT_CLOSE_START <= tt <= PM_SLOT_CLOSE_END:
        minute = (tt.minute // 5) * 5
        floored = tnow.replace(minute=minute, second=0, microsecond=0)
        return floored if floored.time() >= PM_SLOT_CLOSE_START else _combine(trade_day, 11, 30)
    if PM_SLOT_CLOSE_END < tt < time(15, 0):
        return _combine(trade_day, 14, 55)
    if tt >= time(15, 0):
        return _combine(trade_day, 14, 55)
    return None


def compute_market_state(now: Optional[datetime] = None) -> MarketState:
    tnow = _tz_now(now)
    cal_df = _load_calendar_df()
    cal_src = "official" if cal_df is not None else "weekday"

    today = pd.Timestamp(tnow.date())
    is_open = _is_open_day(today, cal_df)
    trade_day = _trade_day_for_now(tnow, cal_df)

    tt = tnow.time()
    if not is_open:
        phase = PHASE_NON_TRADING
        pulse_day = None
        slot_str = None
        data_status = "ok"
    elif tt < time(9, 30):
        phase = PHASE_PREOPEN
        pulse_day = trade_day
        slot_str = None
        data_status = "unavailable"
    elif time(9, 30) <= tt < AM_SLOT_CLOSE_START:
        phase = PHASE_OPEN_NO_FIRST_BAR
        pulse_day = trade_day
        slot_str = None
        data_status = "unavailable"
    elif AM_SLOT_CLOSE_START <= tt <= AM_SLOT_CLOSE_END:
        phase = PHASE_INTRADAY_AM
        pulse_day = trade_day
        slot_str = format_slot_at(last_closed_trade_slot(tnow))
        data_status = "ok"
    elif AM_SLOT_CLOSE_END < tt < time(13, 0):
        phase = PHASE_LUNCH_BREAK
        pulse_day = trade_day
        slot_str = format_slot_at(last_closed_trade_slot(tnow))
        data_status = "ok"
    elif time(13, 0) <= tt < PM_SLOT_CLOSE_START:
        phase = PHASE_INTRADAY_PM
        pulse_day = trade_day
        slot_str = format_slot_at(last_closed_trade_slot(tnow))
        data_status = "ok" if slot_str else "unavailable"
    elif PM_SLOT_CLOSE_START <= tt <= PM_SLOT_CLOSE_END:
        phase = PHASE_INTRADAY_PM
        pulse_day = trade_day
        slot_str = format_slot_at(last_closed_trade_slot(tnow))
        data_status = "ok"
    elif PM_SLOT_CLOSE_END < tt < time(15, 0):
        phase = PHASE_CLOSING_AUCTION
        pulse_day = trade_day
        slot_str = format_slot_at(_combine(trade_day, 14, 55))
        data_status = "ok"
    else:
        phase = PHASE_POSTCLOSE_PENDING
        pulse_day = trade_day
        slot_str = format_slot_at(_combine(trade_day, 14, 55))
        data_status = "close_pending"

    return MarketState(
        market_phase=phase,
        calendar_source=cal_src,
        is_trading_day=is_open,
        target_daybook_effective_day=trade_day,
        target_pulse_trade_day=pulse_day,
        target_pulse_slot_at=slot_str,
        data_status=data_status,
    )
