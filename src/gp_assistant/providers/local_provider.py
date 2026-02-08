from __future__ import annotations

from typing import Dict, Any
from pathlib import Path
import pandas as pd

from ..core.paths import data_dir
from ..core.errors import DataProviderError
from .base import MarketDataProvider


def _infer_ts_code(symbol: str) -> str:
    s = symbol.strip().upper()
    if "." in s:
        return s
    # Heuristic: 6xxxxx -> SH, others -> SZ
    if s.startswith("6"):
        return f"{s}.SH"
    return f"{s}.SZ"


class LocalParquetProvider(MarketDataProvider):
    name = "local"

    def __init__(self, root: Path | None = None):
        self.root = (root or data_dir()) / "bars" / "daily"

    def _file_for(self, symbol: str) -> Path:
        ts_code = _infer_ts_code(symbol)
        return self.root / f"ts_code={ts_code}.parquet"

    def get_daily(self, symbol: str, start: str | None, end: str | None) -> pd.DataFrame:  # noqa: D401
        fp = self._file_for(symbol)
        if not fp.exists():
            raise DataProviderError(f"本地数据不存在: {fp}", symbol=symbol)
        try:
            df = pd.read_parquet(fp)
        except Exception as ex:  # noqa: BLE001
            raise DataProviderError(f"读取本地 parquet 失败: {fp}", symbol=symbol) from ex

        # Soft-normalize common column names; full normalization is done later
        rename_map = {
            "trade_date": "date",
            "ts_code": "symbol",
            "vol": "volume",
        }
        for src, dst in rename_map.items():
            if src in df.columns and dst not in df.columns:
                df[dst] = df[src]

        # If no date column, try index
        if "date" not in df.columns and isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index().rename(columns={df.index.name or "index": "date"})

        if "date" not in df.columns:
            raise DataProviderError("本地数据缺少日期列", symbol=symbol)

        # Attach attrs for normalization
        try:
            df.attrs["volume_unit"] = "hand" if "vol" in df.columns and "volume" not in df.columns else df.attrs.get("volume_unit", None) or "hand"
            # symbol attr
            ts_code = str(df.get("symbol").iloc[0]) if "symbol" in df.columns else _infer_ts_code(symbol)
            df.attrs["symbol"] = ts_code
        except Exception:
            pass

        # Filter by start/end if provided
        try:
            dts = pd.to_datetime(df["date"])  # type: ignore[assignment]
        except Exception:  # noqa: BLE001
            dts = pd.to_datetime(df["date"].astype(str), errors="coerce")
        mask = pd.Series(True, index=df.index)
        if start:
            mask &= dts >= pd.to_datetime(start)
        if end:
            mask &= dts <= pd.to_datetime(end)
        df = df.loc[mask].copy()
        return df

    def healthcheck(self) -> Dict[str, Any]:
        try:
            if self.root.exists():
                any_file = next(self.root.glob("ts_code=*.parquet"), None)
                ok = any_file is not None
                return {"name": self.name, "ok": ok, "reason": None if ok else "本地 daily parquet 不存在"}
            return {"name": self.name, "ok": False, "reason": f"目录不存在: {self.root}"}
        except Exception as e:  # noqa: BLE001
            return {"name": self.name, "ok": False, "reason": str(e)}

    def get_stock_basic(self):  # noqa: ANN001
        # Try a conventional path under data/
        p = (data_dir() / "stocks_basic.parquet")
        import pandas as pd  # local import
        if p.exists():
            try:
                df = pd.read_parquet(p)
                return df
            except Exception as e:  # noqa: BLE001
                raise DataProviderError(f"读取本地 stocks_basic.parquet 失败: {e}")
        # Fallback: try to extract names from daily parquet if present (not guaranteed)
        # Return empty DataFrame if unavailable
        return pd.DataFrame(columns=["ts_code", "name"])  # type: ignore[name-defined]
