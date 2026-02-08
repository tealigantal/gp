# 简介：行情数据提供者抽象基类（接口约定），统一 get_daily/healthcheck 等方法。
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any
import pandas as pd
from ..core.errors import DataProviderError


class MarketDataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_daily(self, symbol: str, start: str | None, end: str | None) -> pd.DataFrame:
        """Return daily bars for symbol between [start, end]. Date format YYYY-MM-DD.

        Columns should include at least: date, open, high, low, close, volume.
        """

    def get_intraday(self, symbol: str, date: str) -> pd.DataFrame:
        raise DataProviderError("intraday not supported", symbol=symbol)

    def get_fundamentals(self, symbol: str):  # noqa: ANN001
        raise DataProviderError("fundamentals not supported", symbol=symbol)

    # Optional: basic info table for names/labels
    def get_stock_basic(self):  # noqa: ANN001
        """Return a DataFrame with at least columns: ts_code/name.

        Default: empty DataFrame; providers may override.
        """
        import pandas as _pd

        return _pd.DataFrame(columns=["ts_code", "name"])  # type: ignore[name-defined]

    @abstractmethod
    def healthcheck(self) -> Dict[str, Any]:
        """Return health info: {name, ok, reason}.
        Must not raise for expected misconfigurations; return reason instead.
        """
