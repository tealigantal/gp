from __future__ import annotations

import math
from typing import Optional, Iterable

import pandas as pd
from curl_cffi import requests as ccrequests

from .base import DataProvider


def _secid_from_ts_code(ts_code: str) -> str:
    # ts_code like 600000.SH or 000001.SZ
    code, exch = ts_code.split('.') if '.' in ts_code else (ts_code, 'SH' if ts_code.startswith('6') else 'SZ')
    prefix = '1' if exch.upper().startswith('SH') or code.startswith('6') else '0'
    return f"{prefix}.{code}"


class EastMoneyCurlProvider(DataProvider):
    base = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    def _req(self, params: dict, retries: int = 0) -> dict:
        backoff = 1.0
        last = None
        for i in range(retries + 1):
            try:
                resp = ccrequests.get(self.base, params=params, timeout=20, impersonate="chrome")
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last = e
                if i == retries:
                    raise
                import time
                time.sleep(backoff)
                backoff *= 2
        raise last  # type: ignore

    def get_stock_basic(self) -> pd.DataFrame:  # pragma: no cover - not used in this provider
        raise NotImplementedError("eastmoney_curl 不提供 stock_basic，请用其他provider获取基础信息")

    def get_trade_calendar(self, start: str, end: str) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError("eastmoney_curl 不提供 trade_calendar，请用其他provider获取")

    def _kline(self, ts_code: str, klt: int, start: Optional[str], end: Optional[str], fqt: int = 0, retries: int = 2, limit: int = 1000000) -> pd.DataFrame:
        secid = _secid_from_ts_code(ts_code)
        params = {
            'secid': secid,
            'klt': klt,
            'fqt': fqt,
            'ut': 'fa5fd1943c7b386f',
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57',
            'lmt': str(limit),
        }
        # beg/end for eastmoney accept YYYYMMDD (or 0 / 20500101)
        if start:
            params['beg'] = start.replace('-', '').replace(':', '').replace(' ', '')[:8]
        else:
            params['beg'] = '0'
        if end:
            params['end'] = end.replace('-', '').replace(':', '').replace(' ', '')[:8]
        else:
            params['end'] = '20500101'
        data = self._req(params, retries=retries)
        arr = (((data or {}).get('data') or {}).get('klines')) or []
        if not arr:
            return pd.DataFrame()
        out = []
        for s in arr:
            parts = str(s).split(',')
            if len(parts) < 7:
                continue
            t, o, c, h, l, v, a = parts[:7]
            out.append({
                'trade_time': t, 'open': float(o), 'high': float(h), 'low': float(l), 'close': float(c),
                'vol': float(v), 'amount': float(a), 'ts_code': ts_code
            })
        df = pd.DataFrame(out)
        # filter by date/time range if provided
        # df already bounded by beg/end from server
        return df.reset_index(drop=True)

    def get_daily_bar(self, ts_code: str, start: str, end: str, adj: Optional[str] = None) -> pd.DataFrame:
        fqt = 0 if not adj or adj == 'none' else 1
        df = self._kline(ts_code, klt=101, start=start, end=end, fqt=fqt)
        if df.empty:
            return df
        # Normalize to daily schema
        df = df.rename(columns={'trade_time': 'trade_date'})
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y%m%d')
        return df[['trade_date','open','high','low','close','vol','amount','ts_code']]

    def get_min_bar(self, ts_code: str, start_dt: str, end_dt: str, freq: str = '5min') -> pd.DataFrame:
        if freq != '5min':
            raise ValueError('eastmoney_curl 仅支持 5min')
        df = self._kline(ts_code, klt=5, start=start_dt, end=end_dt, fqt=0)
        if df.empty:
            return df
        # Ensure time format includes seconds
        df['trade_time'] = pd.to_datetime(df['trade_time']).dt.strftime('%Y-%m-%d %H:%M:%S')
        return df[['trade_time','open','high','low','close','vol','amount','ts_code']]

    def get_namechange(self, ts_code: Optional[str] = None) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError("eastmoney_curl 不提供 namechange")

    def get_announcements(self, start: str, end: str, ts_code: Optional[str] = None) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError("eastmoney_curl 不提供公告")
