from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd


def save_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def load_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def daily_bar_path(data_root: Path, ts_code: str) -> Path:
    return data_root / "bars" / "daily" / f"ts_code={ts_code}.parquet"


def min5_bar_path(data_root: Path, ts_code: str, yyyymmdd: str) -> Path:
    return data_root / "bars" / "min5" / f"ts_code={ts_code}" / f"date={yyyymmdd}.parquet"


def raw_path(data_root: Path, name: str) -> Path:
    return data_root / "raw" / name

