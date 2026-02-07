from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any
import pandas as pd


class MarketDataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_daily(self, symbol: str, start: str | None, end: str | None) -> pd.DataFrame:
        """Return daily bars for symbol between [start, end]. Date format YYYY-MM-DD.

        Columns should include at least: date, open, high, low, close, volume.
        """

    def get_intraday(self, symbol: str, date: str) -> pd.DataFrame:
        raise NotImplementedError("intraday not implemented")

    def get_fundamentals(self, symbol: str):  # noqa: ANN001
        raise NotImplementedError("fundamentals not implemented")

    @abstractmethod
    def healthcheck(self) -> Dict[str, Any]:
        """Return health info: {name, ok, reason}.
        Must not raise for expected misconfigurations; return reason instead.
        """

