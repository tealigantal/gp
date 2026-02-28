from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Set

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
    p = argparse.ArgumentParser(description="Fetch 5min bars for candidate pool (and open positions if any)")
    p.add_argument("--provider", choices=["tushare", "akshare"], default="tushare")
    p.add_argument("--date", required=True)
    return p.parse_args()


def main() -> None:  # pragma: no cover - orchestration
    args = parse_args()
    root = Path.cwd()
    store = LocalParquetStore(root)
    uni_file = root / "universe" / f"candidate_pool_{args.date}.csv"
    if not uni_file.exists():
        raise RuntimeError(f"Missing universe file: {uni_file}")
    uni = pd.read_csv(uni_file)
    syms: Set[str] = set(uni["ts_code"].tolist())

    # Optional: include current holdings from latest results if needed
    # This is a best-effort convenience and safe if file missing.
    pos_file = root / "results" / "current_positions.csv"
    if pos_file.exists():
        pos = pd.read_csv(pos_file)
        syms.update(pos["ts_code"].tolist())

    provider = make_provider(args.provider)
    df = provider.get_min_bar(sorted(syms), start=args.date, end=args.date, freq="5min")
    if df is None or df.empty:
        print("No minute bars fetched.")
        return
    store.write_min5(df)


if __name__ == "__main__":  # pragma: no cover
    main()

