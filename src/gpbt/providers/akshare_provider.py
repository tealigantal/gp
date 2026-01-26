from __future__ import annotations

from typing import Optional
import pandas as pd

from .base import DataProvider


class AkShareProvider(DataProvider):
    def __init__(self):
        import akshare as ak  # type: ignore
        self.ak = ak

    def get_stock_basic(self) -> pd.DataFrame:
        # 主板过滤需结合后续 universe 规则，这里先返回全A股基础表
        df = self.ak.stock_zh_a_spot_em()
        # 构造必要字段：ts_code 可能不可得，仅保留 symbol/name 做后续映射
        # AkShare symbol 格式通常为6位代码，需要拼接交易所后缀在后续步骤完成
        out = pd.DataFrame({
            'symbol': df.get('代码'),
            'name': df.get('名称'),
        }).dropna()
        out['ts_code'] = out['symbol']  # 占位，后续应补交易所后缀
        out['exchange'] = None
        out['market'] = None
        out['list_date'] = None
        out['delist_date'] = None
        return out[['ts_code','symbol','name','exchange','market','list_date','delist_date']]

    def get_trade_calendar(self, start: str, end: str) -> pd.DataFrame:
        cal = self.ak.tool_trade_date_hist_sina()
        cal = cal.rename(columns={'trade_date': 'date'})
        cal['date'] = pd.to_datetime(cal['date']).dt.strftime('%Y%m%d')
        cal = cal[(cal['date'] >= start) & (cal['date'] <= end)]
        return cal[['date']].rename(columns={'date': 'trade_date'}).reset_index(drop=True)

    def get_daily_bar(self, ts_code: str, start: str, end: str, adj: Optional[str] = None) -> pd.DataFrame:
        # AkShare日线接口多样，这里用东财历史
        symbol = ts_code.split('.')[0]
        df = self.ak.stock_zh_a_hist(symbol=symbol, period='daily', adjust='' if (not adj or adj == 'none') else 'qfq')
        if df is None or df.empty:
            return pd.DataFrame(columns=['trade_date','open','high','low','close','vol','amount','ts_code'])
        out = pd.DataFrame({
            'trade_date': pd.to_datetime(df['日期']).dt.strftime('%Y%m%d'),
            'open': df['开盘'],
            'high': df['最高'],
            'low': df['最低'],
            'close': df['收盘'],
            'vol': df['成交量'],
            'amount': df['成交额'],
        })
        out = out[(out['trade_date'] >= start) & (out['trade_date'] <= end)].copy()
        out['ts_code'] = ts_code
        return out.reset_index(drop=True)

    def get_min_bar(self, ts_code: str, start_dt: str, end_dt: str, freq: str = '5min') -> pd.DataFrame:
        symbol = ts_code.split('.')[0]
        df = self.ak.stock_zh_a_hist_min_em(symbol=symbol, period='5', adjust='')
        if df is None or df.empty:
            return pd.DataFrame(columns=['trade_time','open','high','low','close','vol','amount','ts_code'])
        out = pd.DataFrame({
            'trade_time': pd.to_datetime(df['时间']).dt.strftime('%Y-%m-%d %H:%M:%S'),
            'open': df['开盘'],
            'high': df['最高'],
            'low': df['最低'],
            'close': df['收盘'],
            'vol': df['成交量'],
            'amount': df['成交额'],
        })
        out = out[(out['trade_time'] >= start_dt) & (out['trade_time'] <= end_dt)].copy()
        out['ts_code'] = ts_code
        return out.reset_index(drop=True)

    def get_namechange(self, ts_code: Optional[str] = None) -> pd.DataFrame:
        # AkShare缺通用曾用名接口，返回空表以触发“名称包含ST”的弱替代
        return pd.DataFrame(columns=['ts_code','name','start_date','end_date','change_reason'])

    def get_announcements(self, start: str, end: str, ts_code: Optional[str] = None) -> pd.DataFrame:
        # 留空/占位，实际根据可用接口实现
        return pd.DataFrame(columns=['ann_date','ts_code','title'])

