from __future__ import annotations

import os
from typing import Iterable

import pandas as pd

from .base import DataProvider, ProviderError


class TushareProvider(DataProvider):
    def __init__(self) -> None:  # pragma: no cover - network-bound
        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            raise ProviderError(
                "Missing TUSHARE_TOKEN environment variable.",
                api="tushare",
                hint="Export TUSHARE_TOKEN or use --provider akshare",
            )
        try:
            import tushare as ts  # type: ignore
        except Exception as e:  # pragma: no cover - import error
            raise ProviderError("tushare import failed; please `pip install tushare`.", api="tushare", hint=str(e))
        self.ts = ts
        self.pro = ts.pro_api(token)

    def _wrap(self, func_name: str, **kwargs) -> pd.DataFrame:
        try:
            func = getattr(self.pro, func_name)
        except AttributeError as e:  # pragma: no cover
            raise ProviderError(f"Tushare API not found: {func_name}", api=func_name, hint=str(e))
        try:
            return func(**kwargs)
        except Exception as e:
            msg = str(e)
            hint = (
                f"Tushare `{func_name}` failed. If your account lacks permission, consider `--provider akshare`.\n"
                f"Error: {msg}"
            )
            raise ProviderError("Tushare API call failed.", api=func_name, hint=hint)

    def get_stock_basic(self) -> pd.DataFrame:  # pragma: no cover - network-bound
        df = self._wrap("stock_basic", list_status="L", fields="ts_code,name,market,exchange,list_date")
        # heuristics for ST
        df["is_st"] = df["name"].str.contains("ST", case=False, regex=False)
        return df

    def get_trade_calendar(self, start: str, end: str, exchange: str = "SSE") -> pd.DataFrame:  # pragma: no cover
        df = self._wrap("trade_cal", start_date=start, end_date=end, exchange=exchange)
        return df[["cal_date", "is_open"]]

    def get_daily_bar(self, ts_codes: Iterable[str], start: str, end: str) -> pd.DataFrame:  # pragma: no cover
        rows = []
        for code in ts_codes:
            df = self._wrap(
                "daily",
                ts_code=code,
                start_date=start,
                end_date=end,
                fields="ts_code,trade_date,open,high,low,close,vol,amount",
            )
            rows.append(df)
        return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
            columns=["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]
        )

    def get_min_bar(self, ts_codes: Iterable[str], start: str, end: str, freq: str = "5min") -> pd.DataFrame:  # pragma: no cover
        if freq not in {"5min", "5m", "5"}:
            raise ProviderError("Only 5min supported in this project.", api="stk_min")
        rows = []
        for code in ts_codes:
            # Tushare has `pro_bar` for minute with `freq='5min'` but may require permission.
            try:
                df = self.ts.pro_bar(ts_code=code, start_date=start, end_date=end, freq="5min")
            except Exception as e:
                raise ProviderError(
                    "Tushare minute API requires permission.",
                    api="pro_bar(5min)",
                    hint=("If you lack minute permissions, switch to `--provider akshare` (note: AkShare minute data may be recent-only).\n"
                          + str(e)),
                )
            if df is None or df.empty:
                continue
            part = pd.DataFrame()
            part["ts_code"] = df["ts_code"]
            # pro_bar returns `trade_time` as datetime-like or string "YYYY-MM-DD HH:MM:SS"
            tt = pd.to_datetime(df["trade_time"]).dt.strftime("%Y%m%d %H:%M:%S")
            part["trade_time"] = tt
            part["open"] = df["open"]
            part["high"] = df["high"]
            part["low"] = df["low"]
            part["close"] = df["close"]
            part["vol"] = df.get("vol", 0.0)
            part["amount"] = df.get("amount", 0.0)
            rows.append(part)
        return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
            columns=["ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount"]
        )

    def get_namechange(self) -> pd.DataFrame:  # pragma: no cover
        df = self._wrap("namechange", fields="ts_code,name,start_date,end_date")
        return df

    def get_announcements(self, start: str, end: str) -> pd.DataFrame:  # pragma: no cover
        # Tushare announcements API is `anns` or `anndata` depending on plan; try `anns` first.
        try:
            df = self._wrap("anns", start_date=start, end_date=end, fields="ts_code,ann_date,title,category")
        except ProviderError:
            # fallback: return empty but with structure, hint about akshare
            df = pd.DataFrame(columns=["ts_code", "ann_date", "title", "category"])
        return df

