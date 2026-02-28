from __future__ import annotations

"""Generate a tiny offline fixtures dataset under repo root.

Covers:
- 2 symbols, a week of trading days 2025-01-06..2025-01-10
- daily bars
- 5min bars with at least one limit-up buy failure and one day with normal fills
- candidate_pool per day
- trade_calendar
"""

from pathlib import Path
import pandas as pd


def generate(root: Path | None = None) -> None:
    root = Path.cwd() if root is None else Path(root)
    (root / "data/raw").mkdir(parents=True, exist_ok=True)
    (root / "data/bars/daily").mkdir(parents=True, exist_ok=True)
    (root / "data/bars/min5").mkdir(parents=True, exist_ok=True)
    (root / "universe").mkdir(parents=True, exist_ok=True)

    # basics
    basics = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "name": "A", "market": "主板", "exchange": "SZ", "is_st": False, "list_date": "20100101"},
            {"ts_code": "600000.SH", "name": "B", "market": "主板", "exchange": "SH", "is_st": False, "list_date": "20100101"},
        ]
    )
    basics.to_parquet(root / "data" / "raw" / "stock_basic.parquet", index=False)

    # calendar
    cal = pd.DataFrame(
        {"cal_date": ["20250106", "20250107", "20250108", "20250109", "20250110"], "is_open": [1, 1, 1, 1, 1]}
    )
    cal.to_parquet(root / "data" / "raw" / "trade_calendar.parquet", index=False)

    # daily bars
    daily_rows = []
    for d, a, b in [
        ("20250103", 10.0, 10.0),
        ("20250106", 10.0, 10.0),
        ("20250107", 10.2, 10.1),
        ("20250108", 10.1, 10.2),
        ("20250109", 10.0, 10.3),
        ("20250110", 10.3, 10.4),
    ]:
        daily_rows.extend(
            [
                {"ts_code": "000001.SZ", "trade_date": d, "open": a, "high": a, "low": a, "close": a, "vol": 1000, "amount": 10000},
                {"ts_code": "600000.SH", "trade_date": d, "open": b, "high": b, "low": b, "close": b, "vol": 1000, "amount": 10000},
            ]
        )
    ddf = pd.DataFrame(daily_rows)
    # write per ts_code parquet
    for ts, g in ddf.groupby("ts_code"):
        (root / "data" / "bars" / "daily").mkdir(parents=True, exist_ok=True)
        g.sort_values("trade_date").to_parquet(root / "data" / "bars" / "daily" / f"ts_code={ts}.parquet", index=False)

    # min5 bars: include 09:50 and 09:55 for baseline entry; Monday limit-up at 09:55 for 000001.SZ
    def write_min5(ts: str, date: str, rows: list[dict]) -> None:
        # write a parquet at data/bars/min5/ts_code=TS/date=YYYYMMDD.parquet
        p = root / "data" / "bars" / "min5" / f"ts_code={ts}" / f"date={date}.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([{**r, "ts_code": ts} for r in rows])
        df.to_parquet(p, index=False)

    times = ["09:35:00", "09:40:00", "09:45:00", "09:50:00", "09:55:00", "10:00:00"]
    for d in ["20250106", "20250107", "20250108", "20250109", "20250110"]:
        # default normal bars
        for ts in ["000001.SZ", "600000.SH"]:
            rows = []
            base = 10.0 if ts == "000001.SZ" else 10.1
            for i, t in enumerate(times):
                rows.append({"trade_time": f"{d} {t}", "open": base + i * 0.01, "high": base + i * 0.02, "low": base, "close": base + i * 0.02, "vol": 100, "amount": 1000})
            write_min5(ts, d, rows)
    # overwrite Monday 09:55 for 000001.SZ to be one-word limit-up (prev close=10.0 → 11.0)
    write_min5(
        "000001.SZ",
        "20250106",
        [
            {"trade_time": "20250106 09:35:00", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "vol": 100, "amount": 1000},
            {"trade_time": "20250106 09:40:00", "open": 10.1, "high": 10.2, "low": 10.0, "close": 10.2, "vol": 100, "amount": 1000},
            {"trade_time": "20250106 09:45:00", "open": 10.2, "high": 10.3, "low": 10.1, "close": 10.3, "vol": 100, "amount": 1000},
            {"trade_time": "20250106 09:50:00", "open": 10.3, "high": 10.4, "low": 10.2, "close": 10.4, "vol": 100, "amount": 1000},
            # 09:55 one-word limit up with vol=0
            {"trade_time": "20250106 09:55:00", "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "vol": 0, "amount": 0},
            {"trade_time": "20250106 10:00:00", "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "vol": 0, "amount": 0},
        ],
    )

    # candidate pools: simple ordering A then B
    for d in ["20250106", "20250107", "20250108", "20250109", "20250110"]:
        pd.DataFrame({"ts_code": ["000001.SZ", "600000.SH"], "score": [1.0, 0.9]}).to_csv(root / "universe" / f"candidate_pool_{d}.csv", index=False)


if __name__ == "__main__":
    generate()
