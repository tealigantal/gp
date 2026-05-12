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
    calendar_status: str = "unknown"
    calendar_range_start: Optional[str] = None
    calendar_range_end: Optional[str] = None
    next_trading_day: Optional[str] = None
    calendar_error: Optional[str] = None


@dataclass(frozen=True)
class CalendarInfo:
    source: str
    status: str
    range_start: Optional[str] = None
    range_end: Optional[str] = None
    error: Optional[str] = None


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


def _normalize_calendar_df(cal_df) -> pd.DataFrame | None:
    if not isinstance(cal_df, pd.DataFrame) or cal_df.empty:
        return None
    if not {"cal_date", "is_open"} <= set(cal_df.columns):
        return None
    try:
        df = cal_df[["cal_date", "is_open"]].copy()
        df["cal_date"] = (
            df["cal_date"]
            .astype(str)
            .str.strip()
            .str.replace("-", "", regex=False)
            .str.slice(0, 8)
        )
        df = df[df["cal_date"].str.fullmatch(r"\d{8}", na=False)]
        df["is_open"] = pd.to_numeric(df["is_open"], errors="coerce").fillna(0).astype(int)
        df["is_open"] = (df["is_open"] == 1).astype(int)
        df = df.drop_duplicates(subset=["cal_date"], keep="last").sort_values("cal_date").reset_index(drop=True)
        return df if not df.empty else None
    except Exception:
        return None


def _calendar_info(cal_df) -> CalendarInfo:
    df = _normalize_calendar_df(cal_df)
    if cal_df is None:
        return CalendarInfo(source="missing", status="missing", error="trade_calendar_missing")
    if df is None:
        return CalendarInfo(source="invalid", status="invalid", error="trade_calendar_invalid")
    return CalendarInfo(
        source="official",
        status="ok",
        range_start=str(df["cal_date"].min()),
        range_end=str(df["cal_date"].max()),
    )


def _calendar_info_for_day(d: pd.Timestamp, cal_df) -> CalendarInfo:
    info = _calendar_info(cal_df)
    if info.status != "ok":
        return info
    ymd = d.strftime("%Y%m%d")
    if info.range_start and ymd < info.range_start:
        return CalendarInfo(
            source=info.source,
            status="out_of_range",
            range_start=info.range_start,
            range_end=info.range_end,
            error=f"trade_calendar_not_covering_{ymd}",
        )
    if info.range_end and ymd > info.range_end:
        return CalendarInfo(
            source=info.source,
            status="out_of_range",
            range_start=info.range_start,
            range_end=info.range_end,
            error=f"trade_calendar_not_covering_{ymd}",
        )
    return info


def _is_open_day(d: pd.Timestamp, cal_df) -> bool:
    df = _normalize_calendar_df(cal_df)
    if df is None:
        return False
    ymd = d.strftime("%Y%m%d")
    row = df[df["cal_date"] == ymd]
    if row.empty:
        return False
    try:
        return int(row.iloc[0]["is_open"]) == 1
    except Exception:
        return False


def _last_open_day_on_or_before(d: pd.Timestamp, cal_df) -> pd.Timestamp:
    df = _normalize_calendar_df(cal_df)
    if df is not None:
        ymd = d.strftime("%Y%m%d")
        sub = df[(df["cal_date"] <= ymd) & (df["is_open"] == 1)]
        if not sub.empty:
            try:
                return pd.to_datetime(str(sub.iloc[-1]["cal_date"])).normalize()
            except Exception:
                pass
    return d.normalize()


def _next_open_day_on_or_after(d: pd.Timestamp, cal_df) -> Optional[pd.Timestamp]:
    df = _normalize_calendar_df(cal_df)
    if df is None:
        return None
    ymd = d.strftime("%Y%m%d")
    sub = df[(df["cal_date"] >= ymd) & (df["is_open"] == 1)]
    if sub.empty:
        return None
    try:
        return pd.to_datetime(str(sub.iloc[0]["cal_date"])).normalize()
    except Exception:
        return None


def resolve_trading_day_on_or_before(value: str | datetime | date | pd.Timestamp, cal_df=None) -> str:
    base = pd.to_datetime(value).normalize()
    calendar = _load_calendar_df() if cal_df is None else cal_df
    return _last_open_day_on_or_before(base, calendar).strftime("%Y%m%d")


def next_trading_day_on_or_after(value: str | datetime | date | pd.Timestamp, cal_df=None) -> Optional[str]:
    base = pd.to_datetime(value).normalize()
    calendar = _load_calendar_df() if cal_df is None else cal_df
    nxt = _next_open_day_on_or_after(base, calendar)
    return nxt.strftime("%Y%m%d") if nxt is not None else None


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
    cal_df = _load_calendar_df()
    if not _is_open_day(pd.Timestamp(tnow.date()), cal_df):
        return None
    trade_day = _trade_day_for_now(tnow, cal_df)
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

    today = pd.Timestamp(tnow.date())
    cal_info = _calendar_info_for_day(today, cal_df)
    calendar_ready = cal_info.status == "ok"
    is_open = _is_open_day(today, cal_df) if calendar_ready else False
    trade_day = _trade_day_for_now(tnow, cal_df)
    next_open = _next_open_day_on_or_after(today, cal_df)
    next_open_day = next_open.strftime("%Y%m%d") if next_open is not None else None

    tt = tnow.time()
    if not calendar_ready:
        phase = PHASE_NON_TRADING
        pulse_day = None
        slot_str = None
        data_status = f"calendar_{cal_info.status}"
    elif not is_open:
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
        calendar_source=cal_info.source,
        is_trading_day=is_open,
        target_daybook_effective_day=trade_day,
        target_pulse_trade_day=pulse_day,
        target_pulse_slot_at=slot_str,
        data_status=data_status,
        calendar_status=cal_info.status,
        calendar_range_start=cal_info.range_start,
        calendar_range_end=cal_info.range_end,
        next_trading_day=next_open_day,
        calendar_error=cal_info.error,
    )
