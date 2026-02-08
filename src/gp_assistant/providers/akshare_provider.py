from __future__ import annotations

from typing import Dict, Any
import pandas as pd

from ..core.errors import DataProviderError
from .base import MarketDataProvider


class AkShareProvider(MarketDataProvider):
    name = "akshare"

    def __init__(self, timeout_sec: int = 20):
        self.timeout_sec = timeout_sec

    def _import(self):  # late import to avoid hard dependency at import time
        try:
            import akshare as ak  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise DataProviderError(
                f"AkShare 未安装或导入失败: {e}"
            ) from e
        return ak

    def get_daily(self, symbol: str, start: str | None, end: str | None) -> pd.DataFrame:  # noqa: D401
        """Fetch daily kline using AkShare stock_zh_a_hist."""
        ak = self._import()
        # AkShare expects YYYYMMDD
        s = start.replace("-", "") if start else None
        e = end.replace("-", "") if end else None
        try:
            # Try the common A-share endpoint; users may need to pass proper symbol.
            df = ak.stock_zh_a_hist(symbol=symbol, start_date=s, end_date=e, period="daily", adjust="")
        except Exception as ex:  # noqa: BLE001
            raise DataProviderError("AkShare 获取日线数据失败", symbol=symbol) from ex

        if df is None or len(df) == 0:
            raise DataProviderError("AkShare 返回空数据", symbol=symbol)

        # Normalize columns to a common schema
        cols_map = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        }
        for src, dst in cols_map.items():
            if src in df.columns and dst not in df.columns:
                df[dst] = df[src]

        # Ensure required columns exist
        required = ["date", "open", "high", "low", "close"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise DataProviderError(f"AkShare 返回数据缺少列: {missing}", symbol=symbol)

        return df

    def healthcheck(self) -> Dict[str, Any]:
        try:
            # Only import; do not hit network here
            self._import()
            return {"name": self.name, "ok": True, "reason": None}
        except Exception as e:  # noqa: BLE001
            return {"name": self.name, "ok": False, "reason": str(e)}

    # Optional: basic
    def get_stock_basic(self):  # noqa: ANN001
        ak = self._import()
        try:
            df = ak.stock_zh_a_spot_em()
            # Expected columns: 代码, 名称
            import pandas as pd
            res = pd.DataFrame({
                "ts_code": df.get("代码"),
                "name": df.get("名称"),
            })
            return res
        except Exception as e:  # noqa: BLE001
            raise DataProviderError(f"AkShare 获取基础信息失败: {e}")
