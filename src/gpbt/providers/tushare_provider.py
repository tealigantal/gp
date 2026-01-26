from __future__ import annotations

import os
from typing import Optional
import pandas as pd

from .base import DataProvider


class TushareProvider(DataProvider):
    def __init__(self):
        token = os.getenv("TUSHARE_TOKEN")
        if not token:
            raise RuntimeError("TUSHARE_TOKEN not set. Please export your tushare pro token.")
        import tushare as ts  # type: ignore

        ts.set_token(token)
        self.pro = ts.pro_api()
        self._ts = ts

    def get_stock_basic(self) -> pd.DataFrame:
        df = self.pro.stock_basic(market='主板', list_status='L',
                                  fields='ts_code,symbol,name,exchange,market,list_date,delist_date')
        return df

    def get_trade_calendar(self, start: str, end: str) -> pd.DataFrame:
        sse = self.pro.trade_cal(exchange='SSE', start_date=start, end_date=end, is_open='1')
        szse = self.pro.trade_cal(exchange='SZSE', start_date=start, end_date=end, is_open='1')
        cal = pd.concat([sse[['cal_date']].rename(columns={'cal_date': 'trade_date'}),
                         szse[['cal_date']].rename(columns={'cal_date': 'trade_date'})])
        cal = cal.drop_duplicates().sort_values('trade_date').reset_index(drop=True)
        return cal

    def get_daily_bar(self, ts_code: str, start: str, end: str, adj: Optional[str] = None) -> pd.DataFrame:
        # Use pro_bar for flexibility
        df = self._ts.pro_bar(ts_code=ts_code, asset='E', freq='D', start_date=start, end_date=end,
                              adj=None if not adj or adj == 'none' else adj)
        if df is None or df.empty:
            return pd.DataFrame(columns=['trade_date','open','high','low','close','vol','amount','ts_code'])
        df = df[['trade_date','open','high','low','close','vol','amount']].copy()
        df['ts_code'] = ts_code
        return df.sort_values('trade_date').reset_index(drop=True)

    def get_min_bar(self, ts_code: str, start_dt: str, end_dt: str, freq: str = '5min') -> pd.DataFrame:
        df = self.pro.stk_mins(ts_code=ts_code, freq=freq, start_date=start_dt, end_date=end_dt)
        if df is None or df.empty:
            return pd.DataFrame(columns=['trade_time','open','high','low','close','vol','amount','ts_code'])
        # Normalize columns
        # tushare returns: ts_code, trade_time, open, high, low, close, vol, amount
        cols = ['trade_time','open','high','low','close','vol','amount']
        df = df[['trade_time','open','high','low','close','vol','amount']].copy()
        df['ts_code'] = ts_code
        return df.sort_values('trade_time').reset_index(drop=True)

    def get_namechange(self, ts_code: Optional[str] = None) -> pd.DataFrame:
        if ts_code:
            df = self.pro.namechange(ts_code=ts_code,
                                     fields='ts_code,name,start_date,end_date,ann_date,change_reason')
        else:
            df = self.pro.namechange(fields='ts_code,name,start_date,end_date,ann_date,change_reason')
        return df

    def get_announcements(self, start: str, end: str, ts_code: Optional[str] = None) -> pd.DataFrame:
        if ts_code:
            df = self.pro.anns_d(start_date=start, end_date=end, ts_code=ts_code)
        else:
            df = self.pro.anns_d(start_date=start, end_date=end)
        # Ensure required columns
        if df is None or df.empty:
            return pd.DataFrame(columns=['ann_date','ts_code','title'])
        keep = ['ann_date','ts_code','title']
        keep = [c for c in keep if c in df.columns]
        return df[keep].copy()

