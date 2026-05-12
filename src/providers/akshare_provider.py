from __future__ import annotations

import os
from typing import Iterable

import pandas as pd

from .base import DataProvider, ProviderError


class AkshareProvider(DataProvider):
    """AkShare-based provider.

    Notes:
    - Minute data via `stock_zh_a_hist_min_em` may be limited to recent history.
    - Rate limiting may apply; implement polite batching in real-world usage.
    """

    def __init__(self) -> None:  # pragma: no cover - network-bound
        try:
            import akshare as ak  # type: ignore
        except Exception as e:  # pragma: no cover - import error path
            raise ProviderError(
                "AkShare import failed; please `pip install akshare`.", api="akshare", hint=str(e)
            )
        self.ak = ak

    def get_stock_basic(self) -> pd.DataFrame:  # pragma: no cover - network-bound
        df = self.ak.stock_zh_a_spot_em()
        # Map to standard columns; AkShare doesn't expose all basics here.
        out = pd.DataFrame()
        out["ts_code"] = df["代码"].apply(lambda x: f"{x[:6]}.{('SH' if x.startswith('6') else 'SZ')}")
        out["name"] = df["名称"]
        # AkShare lacks list_date/market/exchange in this endpoint; fill best-effort.
        out["list_date"] = ""
        out["market"] = out["ts_code"].str[-2:].map({"SH": "主板", "SZ": "主板"})
        out["exchange"] = out["ts_code"].str[-2:]
        out["is_st"] = out["name"].astype(str).str.contains("ST", case=False, regex=False)
        return out

    def get_trade_calendar(self, start: str, end: str, exchange: str = "SSE") -> pd.DataFrame:  # pragma: no cover
        start_ymd = pd.to_datetime(start).strftime("%Y%m%d")
        end_ymd = pd.to_datetime(end).strftime("%Y%m%d")
        if start_ymd > end_ymd:
            raise ProviderError("Trade calendar start date must be before end date.", api="tool_trade_date_hist_sina")

        df = self.ak.tool_trade_date_hist_sina()
        if df is None or df.empty or "trade_date" not in df.columns:
            raise ProviderError("AkShare returned an empty trade calendar.", api="tool_trade_date_hist_sina")

        open_days = pd.to_datetime(df["trade_date"], errors="coerce").dropna().dt.strftime("%Y%m%d")
        if open_days.empty:
            raise ProviderError("AkShare trade calendar has no parseable trade dates.", api="tool_trade_date_hist_sina")
        if start_ymd < str(open_days.min()) or end_ymd > str(open_days.max()):
            raise ProviderError(
                "AkShare trade calendar does not cover the requested range.",
                api="tool_trade_date_hist_sina",
                hint=f"available={open_days.min()}..{open_days.max()} requested={start_ymd}..{end_ymd}",
            )

        all_days = pd.date_range(start=start_ymd, end=end_ymd, freq="D").strftime("%Y%m%d")
        out = pd.DataFrame({"cal_date": all_days})
        open_set = set(open_days)
        out["is_open"] = out["cal_date"].isin(open_set).astype(int)
        return out[["cal_date", "is_open"]]

    def get_daily_bar(self, ts_codes: Iterable[str], start: str, end: str) -> pd.DataFrame:  # pragma: no cover
        rows = []
        for code in ts_codes:
            symbol = self._to_ak_symbol(code)
            df = self.ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start, end_date=end, adjust="")
            if df is None or df.empty:
                continue
            part = pd.DataFrame()
            part["ts_code"] = code
            part["trade_date"] = df["日期"].str.replace("-", "")
            part["open"] = df["开盘"]
            part["high"] = df["最高"]
            part["low"] = df["最低"]
            part["close"] = df["收盘"]
            part["vol"] = df["成交量"]
            part["amount"] = df.get("成交额", 0.0)
            rows.append(part)
        return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
            columns=["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]
        )

    def get_min_bar(self, ts_codes: Iterable[str], start: str, end: str, freq: str = "5min") -> pd.DataFrame:  # pragma: no cover
        if freq != "5min":
            raise ProviderError("AkShare provider only supports 5min in this project.", api="stock_zh_a_hist_min_em")
        rows = []
        for code in ts_codes:
            symbol = self._to_ak_symbol(code)
            df = self.ak.stock_zh_a_hist_min_em(symbol=symbol, period="5", adjust="")
            if df is None or df.empty:
                continue
            df = df.copy()
            df["trade_time"] = df["时间"].str.replace("-", "").str.replace(":00", ":00:00")
            mask = (df["trade_time"] >= f"{start} 00:00:00") & (df["trade_time"] <= f"{end} 23:59:59")
            df = df[mask]
            part = pd.DataFrame()
            part["ts_code"] = code
            part["trade_time"] = df["trade_time"]
            part["open"] = df["开盘"]
            part["high"] = df["最高"]
            part["low"] = df["最低"]
            part["close"] = df["收盘"]
            part["vol"] = df["成交量"]
            part["amount"] = df.get("成交额", 0.0)
            rows.append(part)
        return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
            columns=["ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount"]
        )

    def get_namechange(self) -> pd.DataFrame:  # pragma: no cover - approximate
        # AkShare lacks a direct name change API in EM endpoints used above; return empty.
        return pd.DataFrame(columns=["ts_code", "name", "start_date", "end_date"])

    def get_announcements(self, start: str, end: str) -> pd.DataFrame:  # pragma: no cover - approximate
        # AkShare has announcements but endpoints vary; keep optional and empty.
        return pd.DataFrame(columns=["ts_code", "ann_date", "title", "category"])

    @staticmethod
    def _to_ak_symbol(ts_code: str) -> str:
        code, exch = ts_code.split(".")
        return ("sh" if exch == "SH" else "sz") + code

