# 简介：交易日历与 as_of 处理的轻量工具，提供当日标识与窗口大小等信息。
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Dict

import zoneinfo

from ..core.config import load_config


def is_trading_day(dt: datetime) -> bool:
    # Minimal calendar: weekdays Mon-Fri are trading days (holiday exceptions not covered)
    # Degrade: treat weekend as non-trading
    return dt.weekday() < 5


def nearest_trading_day(dt: datetime) -> datetime:
    d = dt
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


@dataclass
class TradingWindowState:
    in_A: bool
    in_B: bool
    label: str  # "A"/"B"/"NONE"


def trading_window_now(now: datetime | None = None) -> TradingWindowState:
    cfg = load_config()
    tz = zoneinfo.ZoneInfo(cfg.timezone)
    tnow = (now or datetime.now(tz=tz)).astimezone(tz)
    A_start, A_end = time(9, 35), time(10, 15)
    B_start, B_end = time(14, 30), time(15, 0)
    tt = tnow.time()
    in_A = (tt >= A_start) and (tt <= A_end)
    in_B = (tt >= B_start) and (tt <= B_end)
    label = "A" if in_A else ("B" if in_B else "NONE")
    return TradingWindowState(in_A=in_A, in_B=in_B, label=label)


def calendar_summary() -> Dict[str, str]:
    cfg = load_config()
    tz = zoneinfo.ZoneInfo(cfg.timezone)
    now = datetime.now(tz=tz)
    as_of = nearest_trading_day(now).strftime("%Y-%m-%d")
    tw = trading_window_now(now)
    return {"as_of": as_of, "window": tw.label, "timezone": cfg.timezone}
