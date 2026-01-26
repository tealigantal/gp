from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Optional
import pandas as pd


class DataProvider(ABC):
    @abstractmethod
    def get_stock_basic(self) -> pd.DataFrame:
        """Return main-board stock list with columns:
        ts_code, symbol, name, exchange, market, list_date, delist_date
        """

    @abstractmethod
    def get_trade_calendar(self, start: str, end: str) -> pd.DataFrame:
        """Union SSE+SZSE trading dates in [start,end], column: trade_date (YYYYMMDD)"""

    @abstractmethod
    def get_daily_bar(self, ts_code: str, start: str, end: str, adj: Optional[str] = None) -> pd.DataFrame:
        """Daily OHLCV with columns: trade_date, open, high, low, close, vol, amount, ts_code"""

    @abstractmethod
    def get_min_bar(self, ts_code: str, start_dt: str, end_dt: str, freq: str = "5min") -> pd.DataFrame:
        """Min OHLCV with columns: trade_time, open, high, low, close, vol, amount, ts_code"""

    @abstractmethod
    def get_namechange(self, ts_code: Optional[str] = None) -> pd.DataFrame:
        """Name change table to build ST intervals. Columns: ts_code, name, start_date, end_date, change_reason"""

    @abstractmethod
    def get_announcements(self, start: str, end: str, ts_code: Optional[str] = None) -> pd.DataFrame:
        """Announcements for event factor. Columns must include: ann_date, ts_code, title"""

