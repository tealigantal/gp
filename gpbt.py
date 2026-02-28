from __future__ import annotations

import argparse
import os
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

    s_exp = sub.add_parser("experiment", help="Run experiment grid across strategies/params/scenarios")
    s_exp.add_argument("--config", required=True)
    s_exp.add_argument("--experiments", nargs="*", help="Experiment YAML globs (configs/experiments/*.yaml)")
    s_exp.add_argument("--strategies", nargs="*", help="Strategy YAML globs if not using experiments YAML")
    s_exp.add_argument("--start", required=True)
    s_exp.add_argument("--end", required=True)
    s_exp.add_argument("--exp_id", required=False)
    s_exp.add_argument("--seed", type=int, default=42)

    s_tour = sub.add_parser("tournament", help="Run champion tournament (realistic or oracle)")
    s_tour.add_argument("--config", required=True)
    s_tour.add_argument("--strategies", nargs="+", required=True)
    s_tour.add_argument("--start", required=True)
    s_tour.add_argument("--end", required=True)
    s_tour.add_argument("--mode", choices=["realistic", "oracle"], required=True)
    s_tour.add_argument("--training_window", type=int, default=20)
    s_tour.add_argument("--reselect_interval", choices=["weekly"], default="weekly")
    s_tour.add_argument("--tournament_id", required=False)

    s_doc = sub.add_parser("doctor", help="Sanity check environment")
    s_doc.add_argument("--date", help="Check candidate pool for date YYYYMMDD", required=False)
    s_doc.add_argument("--provider", choices=["tushare", "akshare"], required=False)

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
    elif args.cmd == "experiment":
        argv = [
            "--config",
            args.config,
            "--start",
            args.start,
            "--end",
            args.end,
        ]
        if args.experiments:
            argv += ["--experiments", *args.experiments]
        if args.strategies:
            argv += ["--strategies", *args.strategies]
        if args.exp_id:
            argv += ["--exp_id", args.exp_id]
        argv += ["--seed", str(args.seed)]
        sys.exit(run_module("backtest.experiment", argv))
    elif args.cmd == "tournament":
        argv = [
            "--config",
            args.config,
            "--strategies",
            *args.strategies,
            "--start",
            args.start,
            "--end",
            args.end,
            "--mode",
            args.mode,
            "--training_window",
            str(args.training_window),
            "--reselect_interval",
            args.reselect_interval,
        ]
        if args.tournament_id:
            argv += ["--tournament_id", args.tournament_id]
        sys.exit(run_module("backtest.tournament", argv))
    elif args.cmd == "doctor":
        # Offline self-checks
        from src.providers.local_store import LocalParquetStore
        from datetime import datetime
        root = Path.cwd()
        ok = True
        # Directories
        need_dirs = ["data/raw", "data/bars/daily", "data/bars/min5", "universe", "results"]
        for d in need_dirs:
            p = root / d
            if not p.exists():
                print(f"[doctor] MISSING dir: {p}")
                ok = False
        # Schema checks
        store = LocalParquetStore(root)
        # daily sample
        daily_file = None
        dd = root / "data" / "bars" / "daily"
        if dd.exists():
            files = sorted(dd.glob("ts_code=*.parquet"))
            if files:
                daily_file = files[0]
        if daily_file is None:
            print("[doctor] WARN: no daily parquet found for schema check")
        else:
            try:
                import pandas as pd
                df = pd.read_parquet(daily_file)
                need = {"ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"}
                if not need.issubset(set(df.columns)):
                    print(f"[doctor] INVALID daily schema: missing {need - set(df.columns)} in {daily_file}")
                    ok = False
            except Exception as e:
                print(f"[doctor] ERROR reading daily parquet: {e}")
                ok = False
        # min5 sample
        min5_root = root / "data" / "bars" / "min5"
        min5_file = None
        if min5_root.exists():
            for p in min5_root.glob("ts_code=*/date=*.parquet"):
                min5_file = p
                break
        if min5_file is None:
            print("[doctor] WARN: no min5 parquet found for schema check")
        else:
            try:
                import pandas as pd
                df = pd.read_parquet(min5_file)
                need = {"ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount"}
                if not need.issubset(set(df.columns)):
                    print(f"[doctor] INVALID min5 schema: missing {need - set(df.columns)} in {min5_file}")
                    ok = False
            except Exception as e:
                print(f"[doctor] ERROR reading min5 parquet: {e}")
                ok = False
        # Date-specific candidate pool
        date_arg = getattr(args, "date", None)
        if date_arg:
            f = root / "universe" / f"candidate_pool_{date_arg}.csv"
            if not f.exists():
                print(f"[doctor] MISSING candidate pool file: {f}")
                ok = False
        # Provider env check (tushare)
        provider_arg = getattr(args, "provider", None)
        if provider_arg == "tushare":
            if not (os.environ.get("TUSHARE_TOKEN")):
                print("[doctor] MISSING env TUSHARE_TOKEN for provider=tushare")
                ok = False
        print("[doctor] OK" if ok else "[doctor] FAILED")
        sys.exit(0 if ok else 2)


if __name__ == "__main__":  # pragma: no cover
    main()
