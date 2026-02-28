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
    s_tour.add_argument("--emit_registry", required=False, help="Write champion registry JSON")

    s_srv = sub.add_parser("service", help="Operate service pipeline")
    srv_sub = s_srv.add_subparsers(dest="service_cmd", required=True)
    srv_pre = srv_sub.add_parser("preopen")
    srv_pre.add_argument("--date", required=True)
    srv_pre.add_argument("--topk", type=int, default=10)
    srv_intra = srv_sub.add_parser("intraday")
    srv_intra.add_argument("--date", required=True)
    srv_intra.add_argument("--once", action="store_true", default=True)
    srv_close = srv_sub.add_parser("close")
    srv_close.add_argument("--date", required=True)
    srv_pub = srv_sub.add_parser("publish")
    srv_pub.add_argument("--date", required=True)
    srv_run = srv_sub.add_parser("run")
    srv_run.add_argument("--date", required=False)
    srv_run.add_argument("--every", type=int, default=300)
    srv_run.add_argument("--until", type=str, default="15:00")
    srv_run.add_argument("--once", action="store_true", default=False)

    s_doc = sub.add_parser("doctor", help="Sanity check environment")
    s_doc.add_argument("--date", help="Check candidate pool for date YYYYMMDD", required=False)
    s_doc.add_argument("--provider", choices=["tushare", "akshare"], required=False)
    s_doc.add_argument("--level", choices=["basic", "service", "research"], default="basic")

    # Gate: one-key self-check orchestrator
    s_gate = sub.add_parser("gate", help="Run Gate self-checks (A/B/C/ALL)")
    s_gate.add_argument("--level", choices=["A", "B", "C", "ALL"], default="ALL")
    s_gate.add_argument("--py", dest="py", default="auto", help="python launcher: auto|python|python3|'py -3'")

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
        # experiment module resides under src/
        sys.exit(run_module("src.backtest.experiment", argv))
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
        if args.emit_registry:
            argv += ["--emit_registry", args.emit_registry]
        # tournament module resides under src/
        sys.exit(run_module("src.backtest.tournament", argv))
    elif args.cmd == "service":
        # Use explicit src.service.pipeline to avoid relying on sitecustomize
        if args.service_cmd == "preopen":
            sys.exit(run_module("src.service.pipeline", ["preopen", "--date", args.date, "--topk", str(args.topk)]))
        elif args.service_cmd == "intraday":
            sys.exit(run_module("src.service.pipeline", ["intraday", "--date", args.date, "--once"]))
        elif args.service_cmd == "close":
            sys.exit(run_module("src.service.pipeline", ["close", "--date", args.date]))
        elif args.service_cmd == "publish":
            sys.exit(run_module("src.service.pipeline", ["publish", "--date", args.date]))
        elif args.service_cmd == "run":
            argv = ["run"]
            if args.date:
                argv += ["--date", args.date]
            argv += ["--every", str(args.every), "--until", args.until]
            if args.once:
                argv += ["--once"]
            sys.exit(run_module("src.service.pipeline", argv))
    elif args.cmd == "doctor":
        # Offline self-checks
        from src.providers.local_store import LocalParquetStore
        from datetime import datetime
        root = Path.cwd()
        ok = True
        # Directories
        need_dirs = ["data/raw", "data/bars/daily", "data/bars/min5", "universe", "results", "store", "store/recommend", "store/registry"]
        for d in need_dirs:
            p = root / d
            if not p.exists():
                try:
                    p.mkdir(parents=True, exist_ok=True)
                    print(f"[doctor] CREATE dir: {p}")
                except Exception:
                    print(f"[doctor] MISSING dir: {p}")
                    ok = False
        # Basic config checks
        cfg_path = root / "configs" / "config.yaml"
        if cfg_path.exists():
            try:
                import yaml
                cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
                if not cfg or ("vol_unit" not in cfg and "volume_unit" not in cfg):
                    print("[doctor] MISSING config key: vol_unit (set to 'shares' or explicit unit)")
                    ok = False
            except Exception as e:
                print(f"[doctor] ERROR reading config.yaml: {e}")
                ok = False
        else:
            print("[doctor] MISSING configs/config.yaml")
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
        # Level-based extra checks
        level = getattr(args, "level", "basic")
        if level in ("service", "research"):
            latest = root / "store" / "recommend" / "latest.json"
            if not latest.exists():
                print("[doctor] WARN: store/recommend/latest.json not found (service not published)")
        if level == "research":
            exp_dir = root / "results"
            # not enforcing presence, just a gentle reminder
            pass
        # Provider env check (tushare)
        provider_arg = getattr(args, "provider", None)
        if provider_arg == "tushare":
            if not (os.environ.get("TUSHARE_TOKEN")):
                print("[doctor] MISSING env TUSHARE_TOKEN for provider=tushare")
                ok = False
        print("[doctor] OK" if ok else "[doctor] FAILED")
        sys.exit(0 if ok else 2)
    elif args.cmd == "gate":
        # Detect Python launcher for shell-outs
        def detect_py(user_pref: str) -> list[str]:
            pref = (user_pref or "auto").strip().lower()
            if pref != "auto":
                # return as a shlex-split list; simple handling
                if pref == "python":
                    return ["python"]
                if pref == "python3":
                    return ["python3"]
                if pref in {"py -3", "py3", "py3.11", "py3.12"}:
                    return ["py", "-3"]
                # fallback to literal
                return [pref]

            # auto detection order: python, python3, py -3
            cands: list[list[str]] = [["python"], ["python3"], ["py", "-3"]]
            for cand in cands:
                try:
                    out = subprocess.run(cand + ["-V"], capture_output=True, text=True, timeout=5)
                    if out.returncode == 0:
                        return cand
                except Exception:
                    pass
            # last resort: current interpreter
            return [sys.executable]

        PY = detect_py(getattr(args, "py", "auto"))

        def run_cmd(argv: list[str]) -> int:
            print("$", " ".join(argv))
            p = subprocess.run(argv)
            return int(p.returncode)

        def py_m(mod: str, *more: str) -> list[str]:
            return [*PY, "-m", mod, *more]

        # Define Gates
        gates: dict[str, list[list[str]]] = {}
        # Gate A
        gates["A"] = [
            [*PY, "-m", "compileall", "-q", "."],
            [*PY, "-m", "pytest", "-q"],
            py_m("backtest.runner_weekly", "--config", "configs/config.yaml", "--strategies", *(["configs/strategies/*.yaml"]), "--start", "20250106", "--end", "20250110", "--run_id", "demo_fixture"),
            [*PY, "gpbt.py", "doctor", "--level", "basic"],
        ]
        # Gate B
        gates["B"] = [
            [*PY, "gpbt.py", "service", "preopen", "--date", "20250106"],
            [*PY, "gpbt.py", "service", "intraday", "--date", "20250106", "--once"],
            [*PY, "gpbt.py", "service", "close", "--date", "20250106"],
            [*PY, "gpbt.py", "service", "publish", "--date", "20250106"],
        ]
        # Gate C
        gates["C"] = [
            [*PY, "gpbt.py", "experiment", "--config", "configs/config.yaml", "--experiments", "configs/experiments/demo_grid.yaml", "--start", "20250106", "--end", "20250110", "--exp_id", "demo_matrix"],
            [*PY, "gpbt.py", "tournament", "--config", "configs/config.yaml", "--strategies", *(["configs/strategies/*.yaml"]), "--start", "20250106", "--end", "20250131", "--mode", "realistic", "--training_window", "5", "--reselect_interval", "weekly", "--tournament_id", "demo_real", "--emit_registry", "store/registry/champion.json"],
        ]

        level = (getattr(args, "level", "ALL") or "ALL").upper()
        order = ["A", "B", "C"] if level == "ALL" else [level]

        failed_cmd: list[str] | None = None
        failed_err: str | None = None

        for lv in order:
            print(f"[Gate {lv}] start")
            for cmd in gates.get(lv, []):
                code = run_cmd(cmd)
                if code != 0:
                    failed_cmd = cmd
                    # Try to capture last lines of stderr/stdout by rerunning with capture when safe
                    try:
                        out = subprocess.run(cmd, capture_output=True, text=True)
                        err = (out.stderr or out.stdout or "").strip().splitlines()
                        failed_err = "\n".join(err[-10:])
                    except Exception:
                        failed_err = None
                    print(f"[Gate {lv}] FAIL at: {' '.join(cmd)}")
                    if failed_err:
                        print(f"[Gate {lv}] Error tail:\n{failed_err}")
                    sys.exit(code)
            print(f"[Gate {lv}] PASS")

        # After all, assert required files for B and C (best-effort)
        try:
            missing: list[str] = []
            req = [
                "store/recommend/20250106.json",
                "store/recommend/latest.json",
                "results/live_shadow/20250106/order_log.csv",
                "results/live_shadow/20250106/equity.csv",
                "results/live_shadow/20250106/metrics.json",
                "results/exp_demo_matrix/leaderboard.csv",
                "results/exp_demo_matrix/report.md",
                "results/exp_demo_matrix/manifest.json",
                "results/tournament_demo_real/metrics.json",
                "results/tournament_demo_real/equity.csv",
                "results/tournament_demo_real/switching_log.csv",
                "store/registry/champion.json",
            ]
            for pth in req:
                if not Path(pth).exists():
                    missing.append(pth)
            if missing:
                print("[Gate] WARN: missing expected artifacts:")
                for m in missing:
                    print(" -", m)
        except Exception:
            pass

        print("[Gate] ALL PASS")
        sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()
