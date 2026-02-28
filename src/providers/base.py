from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

import pandas as pd


@dataclass
class ProviderError(Exception):
    message: str
    api: Optional[str] = None
    hint: Optional[str] = None

    def __str__(self) -> str:  # pragma: no cover - trivial
        parts = [self.message]
        if self.api:
            parts.append(f"api={self.api}")
        if self.hint:
            parts.append(f"hint={self.hint}")
        return " | ".join(parts)


class DataProvider(ABC):
    """Abstract interface for market data providers.

    All methods should return pandas.DataFrame with standardized columns.

    Standard fields:
    - stock_basic: ts_code, name, list_date (YYYYMMDD), market, exchange, is_st(bool)
    - trade_calendar: cal_date(YYYYMMDD), is_open(1/0)
    - daily bar: ts_code, trade_date(YYYYMMDD), open, high, low, close, vol, amount
    - min bar (5min): ts_code, trade_time(YYYYMMDD HH:MM:SS), open, high, low, close, vol, amount
    - namechange: ts_code, name, start_date, end_date
    - announcements: ts_code, ann_date(YYYYMMDD), title, category
    """

    @abstractmethod
    def get_stock_basic(self) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def get_trade_calendar(self, start: str, end: str, exchange: str = "SSE") -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def get_daily_bar(self, ts_codes: Iterable[str], start: str, end: str) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def get_min_bar(self, ts_codes: Iterable[str], start: str, end: str, freq: str = "5min") -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def get_namechange(self) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def get_announcements(self, start: str, end: str) -> pd.DataFrame:
        raise NotImplementedError

