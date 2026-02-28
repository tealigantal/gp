from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

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
    p = argparse.ArgumentParser(description="Fetch basics and write to data/raw/ as parquet")
    p.add_argument("--provider", choices=["tushare", "akshare"], default="akshare")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    return p.parse_args()


def main() -> None:  # pragma: no cover - orchestration
    args = parse_args()
    root = Path.cwd()
    store = LocalParquetStore(root)
    try:
        provider = make_provider(args.provider)
    except ProviderError as e:
        print(str(e))
        raise

    basics = provider.get_stock_basic()
    store.write_raw("stock_basic", basics)

    cal = provider.get_trade_calendar(args.start, args.end)
    store.write_raw("trade_calendar", cal)

    namechg = provider.get_namechange()
    store.write_raw("namechange", namechg)

    try:
        anns = provider.get_announcements(args.start, args.end)
        store.write_raw("announcements", anns)
    except ProviderError as e:
        # Optional: user can skip announcements if permission missing
        print(f"Announcements fetch failed: {e}")


if __name__ == "__main__":  # pragma: no cover
    main()
