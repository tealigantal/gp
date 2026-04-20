# 简介：交易日历与 as_of 处理的轻量工具，提供当日标识与窗口大小等信息。
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict

from ..runtime.market_clock import compute_market_state
from ..core.config import load_config


@dataclass
class TradingWindowState:
    label: str  # "A"/"B"/"NONE"


def trading_window_now(now: datetime | None = None) -> TradingWindowState:
    ms = compute_market_state(now)
    # map phases to simple window buckets for legacy callers
    if ms.market_phase in {"INTRADAY_AM", "OPEN_NO_FIRST_BAR"}:
        label = "A"
    elif ms.market_phase in {"INTRADAY_PM", "POSTCLOSE_PENDING"}:
        label = "B"
    else:
        label = "NONE"
    return TradingWindowState(label=label)


def calendar_summary() -> Dict[str, str]:
    ms = compute_market_state()
    cfg = load_config()
    # expose daybook-effective day as YYYY-MM-DD
    as_of = f"{ms.target_daybook_effective_day[:4]}-{ms.target_daybook_effective_day[4:6]}-{ms.target_daybook_effective_day[6:8]}"
    tw = trading_window_now()
    return {"as_of": as_of, "window": tw.label, "timezone": cfg.timezone}


# Thin compatibility wrappers for legacy callers
def is_trading_day(dt: datetime) -> bool:
    return compute_market_state(dt).is_trading_day


def nearest_trading_day(dt: datetime) -> datetime:
    d = dt
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d
