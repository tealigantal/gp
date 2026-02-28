from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd


def _ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class LocalParquetStore:
    root: Path

    # Standards
    # - daily: data/bars/daily/ts_code=000001.SZ.parquet
    # - min5:  data/bars/min5/ts_code=000001.SZ/date=YYYYMMDD.parquet
    # - basics/raw: data/raw/*.parquet

    def __post_init__(self) -> None:  # pragma: no cover - trivial
        self.root = Path(self.root)

    # Raw basics
    def write_raw(self, name: str, df: pd.DataFrame) -> Path:
        path = self.root / "data" / "raw" / f"{name}.parquet"
        _ensure_dir(path)
        df.to_parquet(path, index=False)
        return path

    def read_raw(self, name: str) -> Optional[pd.DataFrame]:
        path = self.root / "data" / "raw" / f"{name}.parquet"
        if path.exists():
            return pd.read_parquet(path)
        return None

    # Daily bars per ts_code
    def daily_path(self, ts_code: str) -> Path:
        return self.root / "data" / "bars" / "daily" / f"ts_code={ts_code}.parquet"

    def append_daily(self, df: pd.DataFrame) -> None:
        # df contains multiple ts_codes
        for ts_code, g in df.groupby("ts_code"):
            path = self.daily_path(ts_code)
            _ensure_dir(path)
            if path.exists():
                old = pd.read_parquet(path)
                merged = (
                    pd.concat([old, g])
                    .drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
                    .sort_values("trade_date")
                )
                merged.to_parquet(path, index=False)
            else:
                g.sort_values("trade_date").to_parquet(path, index=False)

    def read_daily(self, ts_code: str, start: Optional[str] = None, end: Optional[str] = None) -> Optional[pd.DataFrame]:
        path = self.daily_path(ts_code)
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        if start:
            df = df[df["trade_date"] >= start]
        if end:
            df = df[df["trade_date"] <= end]
        return df

    # Min5 bars partitioned by ts_code and date
    def min5_path(self, ts_code: str, trade_date: str) -> Path:
        return self.root / "data" / "bars" / "min5" / f"ts_code={ts_code}" / f"date={trade_date}.parquet"

    def write_min5(self, df: pd.DataFrame) -> None:
        # df contains multiple ts_codes and dates (by trade_time date)
        df = df.copy()
        df["date"] = df["trade_time"].str.slice(0, 8)
        for (ts_code, date), g in df.groupby(["ts_code", "date"]):
            path = self.min5_path(ts_code, date)
            _ensure_dir(path)
            if path.exists():
                old = pd.read_parquet(path)
                merged = (
                    pd.concat([old, g.drop(columns=["date"], errors="ignore")])
                    .drop_duplicates(subset=["ts_code", "trade_time"], keep="last")
                    .sort_values("trade_time")
                )
                merged.to_parquet(path, index=False)
            else:
                g.drop(columns=["date"], errors="ignore").sort_values("trade_time").to_parquet(path, index=False)

    def read_min5(self, ts_code: str, trade_date: str) -> Optional[pd.DataFrame]:
        path = self.min5_path(ts_code, trade_date)
        if not path.exists():
            return None
        return pd.read_parquet(path)

