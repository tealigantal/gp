from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, List

import pandas as pd

from ..providers.base import DataProvider, ProviderError
from ..providers.tushare_provider import TushareProvider
from ..providers.akshare_provider import AkshareProvider
from ..providers.local_store import LocalParquetStore


def make_provider(name: str) -> DataProvider:
    if name == "tushare":
        return TushareProvider()
    elif name == "akshare":
        return AkshareProvider()
    else:
        raise ValueError(f"Unknown provider: {name}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch mainboard daily bars and append parquet store")
    p.add_argument("--provider", choices=["tushare", "akshare"], default="akshare")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--min_list_days", type=int, default=60)
    p.add_argument("--exclude_st", action="store_true", default=True)
    return p.parse_args()


def filter_mainboard(basics: pd.DataFrame, min_list_days: int, end: str, exclude_st: bool = True) -> List[str]:
    b = basics.copy()
    if exclude_st and "is_st" in b.columns:
        b = b[~b["is_st"]]
    # mainboard only: market contains 主板 or exchange in {SH,SZ}
    if "market" in b.columns:
        b = b[b["market"].astype(str).str.contains("主板|Main", na=False)]
    # min_list_days
    if "list_date" in b.columns:
        b = b[b["list_date"] <= str(int(end) - min_list_days)]  # rough filter
    return b["ts_code"].dropna().astype(str).tolist()


def main() -> None:  # pragma: no cover - orchestration
    args = parse_args()
    root = Path.cwd()
    store = LocalParquetStore(root)
    basics = store.read_raw("stock_basic")
    if basics is None:
        # try provider for basics
        provider = make_provider(args.provider)
        basics = provider.get_stock_basic()
        store.write_raw("stock_basic", basics)
    symbols = filter_mainboard_v2(basics, args.min_list_days, args.end, args.exclude_st)
    if not symbols:
        print("No symbols after filtering mainboard/exclusions.")
        return
    provider = make_provider(args.provider)
    # naive batching
    batch = 50
    for i in range(0, len(symbols), batch):
        chunk = symbols[i : i + batch]
        try:
            df = provider.get_daily_bar(chunk, args.start, args.end)
        except ProviderError as e:
            print(str(e))
            continue
        if df is None or df.empty:
            continue
        # Standard columns already ensured by provider
        store.append_daily(df)


if __name__ == "__main__":  # pragma: no cover
    main()
    
def filter_mainboard_v2(basics: pd.DataFrame, min_list_days: int, end: str, exclude_st: bool = True) -> List[str]:
    b = basics.copy()
    if exclude_st and "is_st" in b.columns:
        b = b[~b["is_st"]]
    if "market" in b.columns:
        b = b[b["market"].astype(str).str.contains("????|Main|主板", na=False)]
    if "list_date" in b.columns:
        try:
            ld = pd.to_datetime(b["list_date"].astype(str), format="%Y%m%d", errors="coerce")
            tgt = pd.to_datetime(end, format="%Y%m%d", errors="coerce")
            mask = (ld.notna()) & ((tgt - ld).dt.days >= int(min_list_days))
            b = b[mask]
        except Exception:
            pass
    return b["ts_code"].dropna().astype(str).tolist()
