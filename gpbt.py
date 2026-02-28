from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_module(mod: str, args: list[str]) -> int:
    cmd = [sys.executable, "-m", mod] + args
    return subprocess.call(cmd)


def main() -> None:
    p = argparse.ArgumentParser(description="A股主板短线回测实验系统 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    s_init = sub.add_parser("init", help="Initialize directories")

    s_fetch = sub.add_parser("fetch", help="Fetch basics and daily bars")
    s_fetch.add_argument("--provider", choices=["tushare", "akshare"], default="tushare")
    s_fetch.add_argument("--start", required=True)
    s_fetch.add_argument("--end", required=True)

    s_pool = sub.add_parser("build-candidates", help="Build candidate pool for a date")
    s_pool.add_argument("--date", required=True)
    s_pool.add_argument("--pool_size", type=int, default=20)

    s_pool_range = sub.add_parser("build-candidates-range", help="Build candidate pools for date range")
    s_pool_range.add_argument("--start", required=True)
    s_pool_range.add_argument("--end", required=True)
    s_pool_range.add_argument("--pool_size", type=int, default=20)

    s_min5 = sub.add_parser("fetch-min5-for-pool", help="Fetch 5min bars for a candidate date")
    s_min5.add_argument("--provider", choices=["tushare", "akshare"], default="tushare")
    s_min5.add_argument("--date", required=True)

    s_min5_range = sub.add_parser("fetch-min5-range", help="Fetch 5min bars for candidate pools in range")
    s_min5_range.add_argument("--provider", choices=["tushare", "akshare"], default="tushare")
    s_min5_range.add_argument("--start", required=True)
    s_min5_range.add_argument("--end", required=True)

    s_bt = sub.add_parser("backtest", help="Run weekly backtests")
    s_bt.add_argument("--config", required=True)
    s_bt.add_argument("--strategies", nargs="+", required=True)
    s_bt.add_argument("--start", required=True)
    s_bt.add_argument("--end", required=True)
    s_bt.add_argument("--run_id", required=True)

    _ = sub.add_parser("doctor", help="Sanity check environment")

    args = p.parse_args()
    if args.cmd == "init":
        for d in ["data/raw", "data/bars/daily", "data/bars/min5", "universe", "results"]:
            Path(d).mkdir(parents=True, exist_ok=True)
        print("Initialized directories.")
    elif args.cmd == "fetch":
        code = run_module("scripts.fetch_basics", ["--provider", args.provider, "--start", args.start, "--end", args.end])
        if code != 0:
            sys.exit(code)
        sys.exit(run_module("scripts.fetch_daily", ["--provider", args.provider, "--start", args.start, "--end", args.end]))
    elif args.cmd == "build-candidates":
        sys.exit(run_module("scripts.build_candidate_pool", ["--date", args.date, "--pool_size", str(args.pool_size)]))
    elif args.cmd == "build-candidates-range":
        from datetime import datetime, timedelta
        d0 = datetime.strptime(args.start, "%Y%m%d")
        d1 = datetime.strptime(args.end, "%Y%m%d")
        cur = d0
        while cur <= d1:
            day = cur.strftime("%Y%m%d")
            print(f"Building candidate pool for {day}...")
            run_module("scripts.build_candidate_pool", ["--date", day, "--pool_size", str(args.pool_size)])
            cur += timedelta(days=1)
    elif args.cmd == "fetch-min5-for-pool":
        sys.exit(run_module("scripts.fetch_min5_for_pool", ["--provider", args.provider, "--date", args.date]))
    elif args.cmd == "fetch-min5-range":
        from datetime import datetime, timedelta
        d0 = datetime.strptime(args.start, "%Y%m%d")
        d1 = datetime.strptime(args.end, "%Y%m%d")
        cur = d0
        while cur <= d1:
            day = cur.strftime("%Y%m%d")
            print(f"Fetching 5min for {day}...")
            run_module("scripts.fetch_min5_for_pool", ["--provider", args.provider, "--date", day])
            cur += timedelta(days=1)
    elif args.cmd == "backtest":
        argv = ["--config", args.config, "--strategies", *args.strategies, "--start", args.start, "--end", args.end, "--run_id", args.run_id]
        sys.exit(run_module("backtest.runner_weekly", argv))
    elif args.cmd == "doctor":
        print("Python:", sys.version)
        print("Working dir:", Path.cwd())
        print("Found sitecustomize:", (Path.cwd() / "sitecustomize.py").exists())
        print("Done.")


if __name__ == "__main__":  # pragma: no cover
    main()

