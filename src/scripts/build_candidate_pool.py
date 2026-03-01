from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import pandas as pd

from ..providers.local_store import LocalParquetStore
from ..providers.boards import is_mainboard
from ..selector.selector_v1 import SelectorConfig, explainable_score


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build candidate pool TopK for a trade date")
    p.add_argument("--date", required=True, help="Trade date YYYYMMDD")
    p.add_argument("--pool_size", type=int, default=20)
    p.add_argument("--min_list_days", type=int, default=60)
    p.add_argument("--exclude_st", action="store_true", default=True)
    return p.parse_args()


def main() -> None:  # pragma: no cover - orchestration
    args = parse_args()
    root = Path.cwd()
    store = LocalParquetStore(root)
    basics = store.read_raw("stock_basic")
    if basics is None:
        raise RuntimeError("Missing data/raw/stock_basic.parquet. Run fetch_basics first.")

    # Filter mainboard + exclusions (strict code-based; AkShare-friendly)
    b = basics.copy()
    if args.exclude_st and "is_st" in b.columns:
        b = b[~b["is_st"]]
    # Strict mainboard filter by code rules; ignore provider-specific market labels
    if "ts_code" in b.columns:
        b = b[b["ts_code"].astype(str).map(is_mainboard)]
    if "list_date" in b.columns:
        # Use real date arithmetic for min_list_days
        try:
            ld = pd.to_datetime(b["list_date"].astype(str), format="%Y%m%d", errors="coerce")
            tgt = pd.to_datetime(args.date, format="%Y%m%d", errors="coerce")
            mask = (ld.notna()) & ((tgt - ld).dt.days >= int(args.min_list_days))
            b = b[mask]
        except Exception:
            # fallback: keep all if malformed
            pass

    # Build previous day daily frame for scoring inputs
    rows = []
    for ts in b["ts_code"].astype(str):
        df = store.read_daily(ts, end=args.date)
        if df is None or df.empty:
            continue
        prev = df[df["trade_date"] < args.date].tail(40)  # enough window
        if prev.empty:
            continue
        prev["ts_code"] = ts
        rows.append(prev)
    daily_prev = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]
    )

    # Announcements on current date
    anns = store.read_raw("announcements")
    if anns is None:
        anns = pd.DataFrame(columns=["ts_code", "ann_date", "title", "category"])
    anns_today = anns[anns.get("ann_date", "").astype(str) == args.date]

    scores = explainable_score(daily_prev, anns_today, SelectorConfig())
    # Restrict to filtered universe and take topK
    scores = scores[scores["ts_code"].isin(set(b["ts_code"]))]
    top = scores.head(args.pool_size)
    out_dir = root / "universe"
    out_dir.mkdir(parents=True, exist_ok=True)
    top.to_csv(out_dir / f"candidate_pool_{args.date}.csv", index=False)


if __name__ == "__main__":  # pragma: no cover
    main()
