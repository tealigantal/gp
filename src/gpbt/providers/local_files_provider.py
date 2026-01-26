from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from .base import DataProvider


class LocalFilesProvider(DataProvider):
    def __init__(self, import_root: str | Path = 'data/import'):
        self.import_root = Path(import_root)

    def get_stock_basic(self) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError

    def get_trade_calendar(self, start: str, end: str) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError

    def get_daily_bar(self, ts_code: str, start: str, end: str, adj: Optional[str] = None) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError

    def get_min_bar(self, ts_code: str, start_dt: str, end_dt: str, freq: str = '5min') -> pd.DataFrame:
        if freq != '5min':
            raise ValueError('local_files 仅支持5min')
        # File candidates: CSV or Parquet named as {ts_code}_{YYYYMMDD}.csv(parquet)
        date = start_dt.split(' ')[0].replace('-', '')
        base = self.import_root / 'min5'
        csv_path = base / f"{ts_code}_{date}.csv"
        pq_path = base / f"{ts_code}_{date}.parquet"
        if csv_path.exists():
            df = pd.read_csv(csv_path)
        elif pq_path.exists():
            df = pd.read_parquet(pq_path)
        else:
            return pd.DataFrame()
        # Expect columns: trade_time, open, high, low, close, vol, amount
        if 'ts_code' not in df.columns:
            df['ts_code'] = ts_code
        return df[['trade_time','open','high','low','close','vol','amount','ts_code']]

    def get_namechange(self, ts_code: Optional[str] = None) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError

    def get_announcements(self, start: str, end: str, ts_code: Optional[str] = None) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError

