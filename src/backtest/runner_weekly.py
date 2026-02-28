from __future__ import annotations

import argparse
import glob
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yaml

from .engine import BacktestEngine, CostModel
from .metrics import summarize
from ..providers.local_store import LocalParquetStore


def load_yaml(p: Path) -> dict:
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_strategies(strategy_files: List[Path]):
    from ..strategies.baseline import BaselineStrategy
    from ..strategies.breakout import BreakoutStrategy
    from ..strategies.pullback import PullbackStrategy
    from ..strategies.openrange import OpenRangeStrategy

    mapping = {
        "baseline": BaselineStrategy,
        "breakout": BreakoutStrategy,
        "pullback": PullbackStrategy,
        "openrange": OpenRangeStrategy,
        "open_range": OpenRangeStrategy,
        "open_range_breakout": OpenRangeStrategy,
    }

    strategies = []
    for fp in strategy_files:
        cfg = load_yaml(fp)
        stype = cfg.get("type")
        params = cfg.get("params", {})
        name = cfg.get("name") or fp.stem
        cls = mapping.get(stype)
        if not cls:
            raise ValueError(f"Unknown strategy type in {fp}: {stype}")
        strategies.append(cls(name=name, params=params))
    return strategies


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Weekly backtest runner")
    p.add_argument("--config", required=True)
    p.add_argument("--strategies", nargs="+", required=True, help="Strategy YAML globs e.g. configs/strategies/*.yaml")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--run_id", required=True)
    return p.parse_args()


def main() -> None:  # pragma: no cover - high level orchestration
    args = parse_args()
    root = Path.cwd()
    store = LocalParquetStore(root)
    cfg = load_yaml(Path(args.config))
    # load basics for exchange+st flags if exists
    basics = store.read_raw("stock_basic")
    if basics is None:
        basics = pd.DataFrame(columns=["ts_code", "name", "market", "exchange", "is_st"])  # allow tests to run
    # cost model
    cost = CostModel(
        commission_rate=float(cfg.get("commission_rate", 0.0003)),
        transfer_fee=float(cfg.get("transfer_fee", 0.00002)),
        stamp_duty=float(cfg.get("stamp_duty", 0.001)),
        slippage_bps=float(cfg.get("slippage_bps", 1.0)),
        min_commission=float(cfg.get("min_commission", 5.0)),
    )
    # strategies
    files: List[Path] = []
    for g in args.strategies:
        files.extend([Path(p) for p in glob.glob(g)])
    strategies = load_strategies(files)
    # engines per strategy
    run_dir = root / "results" / f"run_{args.run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # collect all candidate dates within start-end
    uni_dir = root / "universe"
    uni_files = sorted([p for p in uni_dir.glob("candidate_pool_*.csv")])
    dates = [p.stem.split("_")[-1] for p in uni_files]
    dates = [d for d in dates if args.start <= d <= args.end]
    # engines keyed by strategy name
    engines: Dict[str, BacktestEngine] = {}
    for s in strategies:
        res_dir = run_dir / s.name
        engines[s.name] = BacktestEngine(
            strategies=[s],
            initial_cash=float(cfg.get("initial_cash", 1_000_000)),
            cost_model=cost,
            results_dir=res_dir,
            basics=basics,
            daily_prev_close={},
        )

    weekly_rows = []

    # Walk over each day in range
    for d in dates:
        uni_file = uni_dir / f"candidate_pool_{d}.csv"
        if not uni_file.exists():
            continue
        uni_df = pd.read_csv(uni_file)
        universe = uni_df["ts_code"].tolist()
        # For each strategy/engine, decide the universe (same for now)
        # load min5 for universe and any held symbols
        for name, eng in engines.items():
            syms = set(universe)
            syms.update([ts for ts, p in eng.positions.items() if p.shares > 0])
            min5: Dict[str, List[Dict]] = {}
            for ts in sorted(syms):
                df = store.read_min5(ts, d)
                if df is None or df.empty:
                    continue
                # ensure columns
                df = df[["trade_time", "open", "high", "low", "close", "vol", "amount"]]
                bars = [r._asdict() for r in df.itertuples(index=False, name=None)]
                # itertuples name=None returns tuple, fix to dict manually
                bars = [
                    {
                        "trade_time": b[0],
                        "open": float(b[1]),
                        "high": float(b[2]),
                        "low": float(b[3]),
                        "close": float(b[4]),
                        "vol": float(b[5]),
                        "amount": float(b[6]),
                    }
                    for b in bars
                ]
                min5[ts] = bars
            # prev close map from daily store
            prev_map: Dict[str, float] = {}
            for ts in syms:
                daily = store.read_daily(ts, end=d)
                if daily is None or daily.empty:
                    continue
                prev = daily[daily["trade_date"] < d]
                if prev.empty:
                    continue
                prev_map[ts] = float(prev.iloc[-1]["close"])
            eng.daily_prev_close = prev_map
            fail = eng.run_day(d, min5, universe)
            weekly_rows.append({"strategy": name, "date": d, **fail})

    # finalize and metrics; aggregate outputs at run root
    summary_rows = []
    all_trades = []
    all_equity = []
    for name, eng in engines.items():
        eng.finalize()
        trades = pd.read_csv(eng.results_dir / "trades.csv") if (eng.results_dir / "trades.csv").exists() else pd.DataFrame()
        if not trades.empty:
            trades.insert(0, "strategy", name)
            all_trades.append(trades)
        eq = pd.read_csv(eng.results_dir / "daily_equity.csv") if (eng.results_dir / "daily_equity.csv").exists() else pd.DataFrame()
        if not eq.empty:
            eq.insert(0, "strategy", name)
            all_equity.append(eq)
        fails = {"buy_fail": sum(r["buy_fail"] for r in weekly_rows if r["strategy"] == name),
                 "sell_fail": sum(r["sell_fail"] for r in weekly_rows if r["strategy"] == name)}
        st = summarize(trades, eq, fails)
        summary_rows.append(
            {
                "strategy": name,
                "win_rate": st.win_rate,
                "expectancy": st.expectancy,
                "payoff_ratio": st.payoff_ratio,
                "max_drawdown": st.max_drawdown,
                "trades": st.trades,
                "buy_fail": st.buy_fail,
                "sell_fail": st.sell_fail,
            }
        )

    weekly_summary = pd.DataFrame(weekly_rows)
    weekly_summary.to_csv(run_dir / "weekly_summary.csv", index=False)

    if all_trades:
        pd.concat(all_trades, ignore_index=True).to_csv(run_dir / "trades.csv", index=False)
    else:
        pd.DataFrame(columns=["strategy", "time", "ts_code", "side", "price", "shares", "fee", "reason"]).to_csv(
            run_dir / "trades.csv", index=False
        )
    if all_equity:
        pd.concat(all_equity, ignore_index=True).to_csv(run_dir / "daily_equity.csv", index=False)
    else:
        pd.DataFrame(columns=["strategy", "trade_date", "equity", "cash"]).to_csv(run_dir / "daily_equity.csv", index=False)

    metrics = {"strategies": summary_rows}
    with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":  # pragma: no cover
    main()
