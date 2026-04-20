from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional

import zoneinfo

import pandas as pd

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
PHASE_POSTCLOSE_PENDING = "POSTCLOSE_PENDING"
PHASE_POSTCLOSE_READY = "POSTCLOSE_READY"


@dataclass
class MarketState:
    market_phase: str
    calendar_source: str
    is_trading_day: bool
    # canonical targets
    target_daybook_effective_day: str
    target_pulse_trade_day: Optional[str]
    target_pulse_slot_at: Optional[str]
    # data readiness hint (post-close)
    data_status: str  # ok | close_pending | degraded


def _tz_now(now: Optional[datetime]) -> datetime:
    cfg = load_config()
    tz = zoneinfo.ZoneInfo(getattr(cfg, "timezone", "Asia/Shanghai"))
    return (now or datetime.now(tz=tz)).astimezone(tz)


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
    # weekday fallback
    return d.weekday() < 5


def _last_open_day_on_or_before(d: pd.Timestamp, cal_df) -> pd.Timestamp:
    if isinstance(cal_df, pd.DataFrame) and not cal_df.empty and {"cal_date", "is_open"} <= set(cal_df.columns):
        ymd = d.strftime("%Y%m%d")
        sub = cal_df[(cal_df["cal_date"] <= ymd) & (cal_df["is_open"] == 1)]
        if not sub.empty:
            target_str = str(sub.iloc[-1]["cal_date"])  # last open day
            try:
                return pd.to_datetime(target_str).normalize()
            except Exception:
                pass
    # weekday fallback
    dd = d
    while dd.weekday() >= 5:
        dd = dd - pd.Timedelta(days=1)
    return dd.normalize()


def _floor_5m_slot(dt: datetime) -> datetime:
    # floor to previous 5-min boundary
    minute = (dt.minute // 5) * 5
    return dt.replace(minute=minute, second=0, microsecond=0)


def _last_closed_5m_slot(now: datetime) -> Optional[datetime]:
    t = now.time()
    # Trading sessions for main boards
    am_start, am_end = time(9, 30), time(11, 30)
    pm_start, pm_end = time(13, 0), time(14, 55)
    first_bar_close = time(9, 35)

    if t < first_bar_close:
        return None
    if am_start <= t <= am_end:
        return _floor_5m_slot(now)
    if am_end < t < pm_start:
        # lunch break: last closed is 11:30
        return now.replace(hour=11, minute=30, second=0, microsecond=0)
    if pm_start <= t <= pm_end:
        return _floor_5m_slot(now)
    if t > pm_end:
        # after 14:55 but before close auction ends, the last closed 5m is 14:55
        return now.replace(hour=14, minute=55, second=0, microsecond=0)
    return None


def compute_market_state(now: Optional[datetime] = None) -> MarketState:
    tnow = _tz_now(now)
    cal_df = _load_calendar_df()
    cal_src = "official" if cal_df is not None else "weekday"

    today = pd.Timestamp(tnow.date())
    is_open = _is_open_day(today, cal_df)

    # Determine phase by clock first
    tt = tnow.time()
    preopen_start, preopen_end = time(9, 15), time(9, 30)
    first_bar_close = time(9, 35)
    am_start, am_end = time(9, 30), time(11, 30)
    pm_start, pm_end = time(13, 0), time(14, 55)
    close_auction_end = time(15, 0)  # 15:00 is completion boundary for daybook

    if not is_open:
        phase = PHASE_NON_TRADING
    else:
        if tt < preopen_start:
            phase = PHASE_PREOPEN
        elif preopen_start <= tt < preopen_end:
            phase = PHASE_PREOPEN
        elif preopen_end <= tt < first_bar_close:
            phase = PHASE_OPEN_NO_FIRST_BAR
        elif am_start <= tt <= am_end:
            # note: for 9:35..11:30, we treat as AM
            phase = PHASE_INTRADAY_AM
        elif am_end < tt < pm_start:
            phase = PHASE_LUNCH_BREAK
        elif pm_start <= tt <= pm_end:
            phase = PHASE_INTRADAY_PM
        elif pm_end < tt < close_auction_end:
            # closing auction till 15:00 still intraday for 5m purposes
            phase = PHASE_INTRADAY_PM
        else:
            # >= 15:00 local
            # we cannot know if close data is ready here; caller may degrade to pending
            phase = PHASE_POSTCLOSE_PENDING

    # Targets
    # daybook_effective_day: last completed day before close; after 15:00 -> today
    if phase == PHASE_POSTCLOSE_PENDING:
        target_day = today.strftime("%Y%m%d")
        data_status = "close_pending"
    elif phase == PHASE_NON_TRADING:
        target_day = _last_open_day_on_or_before(today - pd.Timedelta(days=0), cal_df).strftime("%Y%m%d")
        data_status = "ok"
    else:
        # pre-open and intraday -> previous completed day
        prev = _last_open_day_on_or_before(today - pd.Timedelta(days=1), cal_df)
        target_day = prev.strftime("%Y%m%d")
        data_status = "ok"

    # pulse trade day and slot
    if phase in {PHASE_INTRADAY_AM, PHASE_INTRADAY_PM, PHASE_OPEN_NO_FIRST_BAR, PHASE_LUNCH_BREAK} and is_open:
        pulse_day = today.strftime("%Y%m%d")
        slot_dt = _last_closed_5m_slot(tnow)
        slot_str = slot_dt.strftime("%Y-%m-%d %H:%M:%S") if slot_dt else None
    else:
        pulse_day = None
        slot_str = None

    # Post-close ready detection is left to higher layers; we default PENDING here
    market_phase = phase
    return MarketState(
        market_phase=market_phase,
        calendar_source=cal_src,
        is_trading_day=is_open,
        target_daybook_effective_day=target_day,
        target_pulse_trade_day=pulse_day,
        target_pulse_slot_at=slot_str,
        data_status=data_status,
    )

