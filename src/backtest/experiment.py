from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml

from .engine import BacktestEngine, CostModel
from .metrics import summarize
from ..providers.local_store import LocalParquetStore


# -----------------------------
# Utilities
# -----------------------------


def _load_yaml(p: Path) -> dict:
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _json_hash(obj: dict) -> str:
    s = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:10]


def _get_git_commit(root: Path) -> Optional[str]:  # pragma: no cover - best effort
    try:
        head = (root / ".git" / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head.split(" ", 1)[1].strip()
            ref_path = root / ".git" / ref
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8").strip()
        else:
            return head
    except Exception:
        return None


# -----------------------------
# Data cache to avoid repeated parquet IO
# -----------------------------


@dataclass
class DataCache:
    store: LocalParquetStore
    # caches
    min5_cache: Dict[Tuple[str, str], Optional[pd.DataFrame]] = None
    daily_cache: Dict[str, Optional[pd.DataFrame]] = None

    def __post_init__(self):  # pragma: no cover - trivial
        if self.min5_cache is None:
            self.min5_cache = {}
        if self.daily_cache is None:
            self.daily_cache = {}

    def get_min5(self, ts_code: str, date: str) -> Optional[pd.DataFrame]:
        key = (ts_code, date)
        if key not in self.min5_cache:
            self.min5_cache[key] = self.store.read_min5(ts_code, date)
        return self.min5_cache[key]

    def get_daily(self, ts_code: str) -> Optional[pd.DataFrame]:
        if ts_code not in self.daily_cache:
            self.daily_cache[ts_code] = self.store.read_daily(ts_code)
        return self.daily_cache[ts_code]


# -----------------------------
# Experiment config model
# -----------------------------


@dataclass
class Scenario:
    name: str
    commission_rate: Optional[float] = None
    transfer_fee: Optional[float] = None
    stamp_duty: Optional[float] = None
    slippage_bps: Optional[float] = None
    min_commission: Optional[float] = None

    def apply_to(self, base: CostModel) -> CostModel:
        return CostModel(
            commission_rate=float(self.commission_rate if self.commission_rate is not None else base.commission_rate),
            transfer_fee=float(self.transfer_fee if self.transfer_fee is not None else base.transfer_fee),
            stamp_duty=float(self.stamp_duty if self.stamp_duty is not None else base.stamp_duty),
            slippage_bps=float(self.slippage_bps if self.slippage_bps is not None else base.slippage_bps),
            min_commission=float(self.min_commission if self.min_commission is not None else base.min_commission),
        )


@dataclass
class GridItem:
    strategy_file: Path
    params_grid: Dict[str, List]

    def expand(self) -> List[Dict]:
        # Cartesian product of params_grid
        keys = list(self.params_grid.keys())
        if not keys:
            return [{}]
        values = [self.params_grid[k] for k in keys]
        combos: List[Dict] = []
        def _rec(i: int, cur: Dict):
            if i == len(keys):
                combos.append(cur.copy())
                return
            for v in values[i]:
                cur[keys[i]] = v
                _rec(i + 1, cur)
        _rec(0, {})
        return combos


@dataclass
class ExperimentSpec:
    exp_id: str
    grid: List[GridItem]
    scenarios: List[Scenario]
    leaderboard_metric: str = "sharpe"
    min_trades: int = 5
    score_weights: Dict[str, float] = None  # e.g., {"sharpe": 1.0, "mdd": -0.5}

    @staticmethod
    def from_yaml(p: Path) -> "ExperimentSpec":
        obj = _load_yaml(p)
        eid = str(obj.get("exp_id") or p.stem)
        grid_cfg = obj.get("grid", [])
        grid = []
        for g in grid_cfg:
            grid.append(GridItem(strategy_file=Path(g["strategy_file"]), params_grid=g.get("params", {})))
        scens = []
        for s in obj.get("scenarios", [{"name": "base"}]):
            scens.append(Scenario(**s))
        weights = obj.get("score_weights", {"sharpe": 1.0, "max_drawdown": -0.5})
        return ExperimentSpec(exp_id=eid, grid=grid, scenarios=scens, leaderboard_metric=str(obj.get("leaderboard_metric", "sharpe")), min_trades=int(obj.get("min_trades", 5)), score_weights=weights)


# -----------------------------
# Metric helpers
# -----------------------------


def daily_returns(equity: pd.Series) -> pd.Series:
    if equity is None or equity.empty:
        return pd.Series(dtype=float)
    r = equity.pct_change().fillna(0.0)
    return r


def sharpe_ratio(returns: pd.Series, *, periods_per_year: int = 252) -> float:
    if returns is None or len(returns) < 2:
        return 0.0
    mu = float(returns.mean())
    sigma = float(returns.std(ddof=1))
    if sigma == 0:
        return 0.0
    return float((mu / sigma) * np.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, *, periods_per_year: int = 252) -> float:
    if returns is None or len(returns) < 2:
        return 0.0
    mu = float(returns.mean())
    downside = returns[returns < 0]
    dd = float(downside.std(ddof=1)) if len(downside) >= 2 else 0.0
    if dd == 0:
        return 0.0
    return float((mu / dd) * np.sqrt(periods_per_year))


def cagr_from_equity(eq: pd.Series, dates: Iterable[str]) -> float:
    if eq is None or eq.empty:
        return 0.0
    start = float(eq.iloc[0])
    end = float(eq.iloc[-1])
    if start <= 0 or end <= 0:
        return 0.0
    n_days = max(1, len(eq))
    years = n_days / 252.0
    return float((end / start) ** (1 / years) - 1.0) if years > 0 else 0.0


def bootstrap_ci(arr: np.ndarray, *, n: int = 1000, alpha_low: float = 0.05, alpha_high: float = 0.95) -> Tuple[float, float]:
    if arr is None or len(arr) == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(42)
    means = []
    for _ in range(n):
        sample = rng.choice(arr, size=len(arr), replace=True)
        means.append(float(np.mean(sample)))
    means = np.sort(np.array(means))
    il = int(alpha_low * len(means))
    ih = int(alpha_high * len(means))
    return float(means[il]), float(means[min(ih, len(means) - 1)])


def ztest_pvalue(mean: float, std: float, n: int) -> float:
    if n <= 1 or std <= 0:
        return 1.0
    z = mean / (std / np.sqrt(n))
    # two-sided p-value using normal CDF approximation
    from math import erf, sqrt
    p = 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2))))
    return float(max(0.0, min(1.0, p)))


# -----------------------------
# Loading strategies
# -----------------------------


def _load_strategy_class_map():
    from ..strategies.baseline import BaselineStrategy
    from ..strategies.breakout import BreakoutStrategy
    from ..strategies.pullback import PullbackStrategy
    from ..strategies.openrange import OpenRangeStrategy

    return {
        "baseline": BaselineStrategy,
        "breakout": BreakoutStrategy,
        "pullback": PullbackStrategy,
        "openrange": OpenRangeStrategy,
        "open_range": OpenRangeStrategy,
        "open_range_breakout": OpenRangeStrategy,
    }


def load_strategy_from_file(fp: Path):
    mp = _load_strategy_class_map()
    cfg = _load_yaml(fp)
    stype = cfg.get("type")
    params = cfg.get("params", {})
    name = cfg.get("name") or fp.stem
    cls = mp.get(stype)
    if not cls:
        return None
    return cls(name=name, params=params)


# -----------------------------
# Argument parsing
# -----------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Experiment Runner: multi-strategy, multi-params, multi-scenario")
    p.add_argument("--config", required=True)
    p.add_argument("--experiments", nargs="+", help="Experiment YAML globs under configs/experiments/*.yaml")
    p.add_argument("--strategies", nargs="*", help="Strategy YAML globs (if not using experiments YAML)")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--exp_id", default=None)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


# -----------------------------
# Core runner
# -----------------------------


def _collect_dates(store: LocalParquetStore, start: str, end: str, root: Path) -> Tuple[List[str], Dict[str, bool]]:
    uni_dir = root / "universe"
    uni_files = sorted([p for p in uni_dir.glob("candidate_pool_*.csv")])
    pool_dates = sorted([p.stem.split("_")[-1] for p in uni_files])
    pool_dates = [d for d in pool_dates if start <= d <= end]

    cal = store.read_raw("trade_calendar")
    if cal is not None and not cal.empty:
        cal = cal.copy()
        cal = cal[(cal["cal_date"] >= start) & (cal["cal_date"] <= end) & (cal["is_open"] == 1)]
        cal_dates = cal["cal_date"].astype(str).tolist()
        dates = [d for d in cal_dates if d in set(pool_dates)]
        import datetime as _dt
        def is_week_last(idx: int) -> bool:
            if idx == len(cal_dates) - 1:
                return True
            d0 = _dt.datetime.strptime(cal_dates[idx], "%Y%m%d").isocalendar().week
            d1 = _dt.datetime.strptime(cal_dates[idx + 1], "%Y%m%d").isocalendar().week
            return d0 != d1
        week_last_map: Dict[str, bool] = {cal_dates[i]: is_week_last(i) for i in range(len(cal_dates))}
    else:
        dates = pool_dates
        week_last_map = {d: (i == len(dates) - 1 or (i + 1 < len(dates) and dates[i][:6] != dates[i + 1][:6])) for i, d in enumerate(dates)}
    return dates, week_last_map


def _expand_experiments(experiment_files: List[Path]) -> Tuple[str, List[Tuple[Path, Dict]], List[Scenario]]:
    # For now, only a single experiment spec is supported; if multiple are provided, use the first
    if not experiment_files:
        raise ValueError("No experiments YAML provided; pass --experiments configs/experiments/*.yaml")
    spec = ExperimentSpec.from_yaml(experiment_files[0])
    pairs: List[Tuple[Path, Dict]] = []
    for item in spec.grid:
        for params in item.expand():
            pairs.append((item.strategy_file, params))
    return spec.exp_id, pairs, spec.scenarios


def _per_trade_pnl(trades: pd.DataFrame) -> np.ndarray:
    if trades is None or trades.empty:
        return np.array([], dtype=float)
    pnl_list = []
    open_pos: Dict[str, Tuple[float, int]] = {}
    for r in trades.itertuples():
        if r.side == "BUY":
            open_pos[r.ts_code] = (r.price, r.shares)
        elif r.side == "SELL":
            if r.ts_code in open_pos:
                buy_px, buy_sh = open_pos.pop(r.ts_code)
                sh = min(buy_sh, r.shares)
                pnl = (r.price - buy_px) * sh - r.fee
                pnl_list.append(float(pnl))
    return np.array(pnl_list, dtype=float)


def run_experiment():  # pragma: no cover - orchestration heavy
    args = parse_args()
    np.random.seed(args.seed)
    root = Path.cwd()
    store = LocalParquetStore(root)
    data = DataCache(store)
    cfg = _load_yaml(Path(args.config))
    basics = store.read_raw("stock_basic")
    if basics is None:
        basics = pd.DataFrame(columns=["ts_code", "name", "market", "exchange", "is_st"])  # tolerate missing basics

    # base cost model from config
    base_cost = CostModel(
        commission_rate=float(cfg.get("commission_rate", 0.0003)),
        transfer_fee=float(cfg.get("transfer_fee", 0.00002)),
        stamp_duty=float(cfg.get("stamp_duty", 0.001)),
        slippage_bps=float(cfg.get("slippage_bps", 1.0)),
        min_commission=float(cfg.get("min_commission", 5.0)),
    )

    # Expand experiments
    if args.experiments:
        exp_files: List[Path] = []
        for g in args.experiments:
            exp_files.extend([Path(p) for p in glob.glob(g)])
        exp_id_default, pair_list, scenarios = _expand_experiments(exp_files)
    else:
        # Fallback: treat strategies as fixed without grid, one base scenario
        files: List[Path] = []
        for g in args.strategies or []:
            files.extend([Path(p) for p in glob.glob(g)])
        pair_list = [(fp, _load_yaml(fp).get("params", {})) for fp in files]
        scenarios = [Scenario(name="base")]
        exp_id_default = "adhoc"

    exp_id = args.exp_id or exp_id_default
    exp_dir = root / "results" / f"exp_{exp_id}"
    exp_dir.mkdir(parents=True, exist_ok=True)

    # Dates
    dates, week_last_map = _collect_dates(store, args.start, args.end, root)

    # Instantiate engines for each (strategy, params, scenario)
    engines: Dict[str, BacktestEngine] = {}
    run_rows: List[Dict] = []
    # keep meta mapping for later
    run_meta: Dict[str, Dict] = {}

    for (fp, params) in pair_list:
        st_cfg = _load_yaml(fp)
        stype = st_cfg.get("type")
        name = st_cfg.get("name") or fp.stem
        StrategyCls = _load_strategy_class_map().get(stype)
        if not StrategyCls:
            continue
        for scen in scenarios:
            scen_name = scen.name
            full_params = dict(st_cfg.get("params", {}))
            full_params.update(params)
            st = StrategyCls(name=name, params=full_params)
            params_hash = _json_hash(full_params)
            run_id = f"{name}_{params_hash}_{scen_name}"
            cost = scen.apply_to(base_cost)
            eng = BacktestEngine(
                strategies=[st],
                initial_cash=float(cfg.get("initial_cash", 1_000_000.0)),
                cost_model=cost,
                results_dir=exp_dir / run_id,
                basics=basics,
                daily_prev_close={},
            )
            engines[run_id] = eng
            run_rows.append({
                "run_id": run_id,
                "strategy": name,
                "params_hash": params_hash,
                "scenario": scen_name,
                "params": json.dumps(full_params, ensure_ascii=False, sort_keys=True),
            })
            run_meta[run_id] = {"strategy": name, "params": full_params, "scenario": scen_name}

    # Persist runs.csv
    pd.DataFrame(run_rows).to_csv(exp_dir / "runs.csv", index=False)

    # Walk days and execute using shared day data
    for d in dates:
        uni_file = root / "universe" / f"candidate_pool_{d}.csv"
        if not uni_file.exists():
            continue
        uni_df = pd.read_csv(uni_file)
        universe = uni_df["ts_code"].tolist()

        # Build symbol set across all engines: union held + universe
        syms = set(universe)
        for eng in engines.values():
            syms.update([ts for ts, p in eng.positions.items() if p.shares > 0])
        syms = sorted(syms)

        # Read min5 per symbol once
        min5: Dict[str, List[Dict]] = {}
        for ts in syms:
            df = data.get_min5(ts, d)
            if df is None or df.empty:
                continue
            df = df[["trade_time", "open", "high", "low", "close", "vol", "amount"]]
            tup = list(df.itertuples(index=False, name=None))
            bars = [
                {
                    "trade_time": t[0],
                    "open": float(t[1]),
                    "high": float(t[2]),
                    "low": float(t[3]),
                    "close": float(t[4]),
                    "vol": float(t[5]),
                    "amount": float(t[6]),
                }
                for t in tup
            ]
            min5[ts] = bars

        # prev close map from daily cache
        prev_map: Dict[str, float] = {}
        for ts in syms:
            daily = data.get_daily(ts)
            if daily is None or daily.empty:
                continue
            prev = daily[daily["trade_date"] < d]
            if prev.empty:
                continue
            prev_map[ts] = float(prev.iloc[-1]["close"])

        # Feed each engine
        is_week_last = False
        # If week_last_map is available for this date
        is_week_last = bool(week_last_map.get(d, False))
        for eng in engines.values():
            eng.daily_prev_close = prev_map
            eng.run_day(d, min5, universe, is_week_last=is_week_last)

    # Finalize and metrics for each run
    metrics_rows: List[Dict] = []
    leader_rows: List[Dict] = []

    for run_id, eng in engines.items():
        eng.finalize()
        trades_path = eng.results_dir / "trades.csv"
        equity_path = eng.results_dir / "daily_equity.csv"
        if trades_path.exists():
            try:
                trades = pd.read_csv(trades_path)
            except Exception:
                trades = pd.DataFrame(columns=["time", "ts_code", "side", "price", "shares", "fee", "reason"])  # empty
        else:
            trades = pd.DataFrame()
        if equity_path.exists():
            try:
                eq = pd.read_csv(equity_path)
            except Exception:
                eq = pd.DataFrame(columns=["trade_date", "equity", "cash"])  # empty
        else:
            eq = pd.DataFrame()

        fails = {k: 0 for k in ("buy_fail", "sell_fail", "pending_bar_count", "reject_buy", "reject_sell")}
        st = summarize(trades, eq, fails)
        eq_series = eq["equity"] if not eq.empty else pd.Series(dtype=float)
        rets = daily_returns(eq_series)
        sharpe = sharpe_ratio(rets)
        sortino = sortino_ratio(rets)
        cagr = cagr_from_equity(eq_series, eq["trade_date"] if not eq.empty else [])
        # turnover approximation: sum traded notional / avg equity
        notional = float((trades["price"] * trades["shares"]).sum()) if not trades.empty else 0.0
        avg_equity = float(eq_series.mean()) if len(eq_series) else 0.0
        turnover = float(notional / avg_equity) if avg_equity > 0 else 0.0
        # fill rate: executed BUY / (BUY + CANCEL_BUY + REJECT_BUY)
        if not trades.empty:
            buy_exec = int((trades["side"] == "BUY").sum())
            buy_cancel = int((trades["side"] == "CANCEL_BUY").sum())
            buy_reject = int((trades["side"] == "REJECT_BUY").sum())
            total_buy = buy_exec + buy_cancel + buy_reject
            fill_rate = float(buy_exec / total_buy) if total_buy > 0 else 0.0
        else:
            fill_rate = 0.0

        # Bootstrap CI for expectancy and Sharpe
        pnl_arr = _per_trade_pnl(trades)
        exp_p05, exp_p95 = bootstrap_ci(pnl_arr, n=400) if len(pnl_arr) else (0.0, 0.0)
        # approximate Sharpe CI via bootstrap of daily returns mean
        sr_samples = []
        if len(rets) > 5:
            rng = np.random.default_rng(42)
            for _ in range(400):
                samp = rng.choice(rets.values, size=len(rets), replace=True)
                sr_samples.append(sharpe_ratio(pd.Series(samp)))
            sr_arr = np.sort(np.array(sr_samples))
            sr_p05 = float(sr_arr[int(0.05 * len(sr_arr))])
            sr_p95 = float(sr_arr[int(0.95 * len(sr_arr))])
        else:
            sr_p05 = 0.0
            sr_p95 = 0.0

        # Multiple comparisons: simple Bonferroni based on per-trade PnL mean > 0
        n_trials = max(1, len(engines))
        mu = float(pnl_arr.mean()) if len(pnl_arr) else 0.0
        sd = float(pnl_arr.std(ddof=1)) if len(pnl_arr) >= 2 else 0.0
        p_raw = ztest_pvalue(mu, sd, len(pnl_arr)) if len(pnl_arr) else 1.0
        p_adj = min(1.0, p_raw * n_trials)

        row = {
            "run_id": run_id,
            "strategy": run_meta[run_id]["strategy"],
            "params_hash": _json_hash(run_meta[run_id]["params"]),
            "scenario": run_meta[run_id]["scenario"],
            "CAGR": cagr,
            "Sharpe": sharpe,
            "Sharpe_p05": sr_p05,
            "Sharpe_p95": sr_p95,
            "Sortino": sortino,
            "max_drawdown": st.max_drawdown,
            "win_rate": st.win_rate,
            "expectancy": st.expectancy,
            "expectancy_p05": exp_p05,
            "expectancy_p95": exp_p95,
            "payoff_ratio": st.payoff_ratio,
            "turnover": turnover,
            "fill_rate": fill_rate,
            "buy_fail": st.buy_fail,
            "sell_fail": st.sell_fail,
            "pending_bar_count": st.pending_bar_count,
            "n_trades": st.trades,
            "n_trials": n_trials,
            "p_value_raw": p_raw,
            "p_value_adj": p_adj,
        }
        metrics_rows.append(row)

    metrics_df = pd.DataFrame(metrics_rows)
    metrics_df.to_csv(exp_dir / "metrics.csv", index=False)

    # Leaderboard: sort using Sharpe p05 then drawdown and trades threshold
    if not metrics_df.empty:
        lb = metrics_df.copy()
        lb = lb[lb["n_trades"] >= 1]  # keep at least 1 trade
        # Score: configurable weights
        w_sharpe = 1.0
        w_mdd = -0.5
        score = w_sharpe * lb["Sharpe_p05"].fillna(0.0) + w_mdd * lb["max_drawdown"].fillna(0.0)
        lb.insert(1, "score", score)
        lb = lb.sort_values(["score", "Sharpe_p05"], ascending=[False, False])
        lb.to_csv(exp_dir / "leaderboard.csv", index=False)
    else:
        pd.DataFrame().to_csv(exp_dir / "leaderboard.csv", index=False)

    # Slippage sensitivity: pivot by params_hash across scenarios
    if not metrics_df.empty:
        cols = ["params_hash", "scenario", "Sharpe", "max_drawdown", "turnover", "fill_rate", "win_rate"]
        sens = metrics_df[cols].copy()
        sens.to_csv(exp_dir / "slippage_sensitivity.csv", index=False)

    # Manifest
    manifest = {
        "exp_id": exp_id,
        "config": str(Path(args.config).as_posix()),
        "start": args.start,
        "end": args.end,
        "seed": int(args.seed),
        "git_commit": _get_git_commit(root),
        "deps": {"pandas": pd.__version__, "numpy": np.__version__},
        "n_runs": len(engines),
    }
    (exp_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # Report
    report_path = exp_dir / "report.md"
    try:
        _write_report(exp_dir, report_path)
    except Exception as e:  # pragma: no cover - robustness only
        report_path.write_text(f"Report generation failed: {e}", encoding="utf-8")


def _write_report(exp_dir: Path, out_path: Path) -> None:
    runs = pd.read_csv(exp_dir / "runs.csv") if (exp_dir / "runs.csv").exists() else pd.DataFrame()
    metrics = pd.read_csv(exp_dir / "metrics.csv") if (exp_dir / "metrics.csv").exists() else pd.DataFrame()
    leaderboard = pd.read_csv(exp_dir / "leaderboard.csv") if (exp_dir / "leaderboard.csv").exists() else pd.DataFrame()
    # Header
    lines: List[str] = []
    lines.append(f"# Experiment Report: {exp_dir.name}")
    if not runs.empty:
        strategies = runs["strategy"].nunique()
        params = runs["params_hash"].nunique()
        scenarios = runs["scenario"].nunique()
    else:
        strategies = params = scenarios = 0
    lines.append("")
    lines.append(f"- Strategies: {strategies}")
    lines.append(f"- Param combos: {params}")
    lines.append(f"- Scenarios: {scenarios}")
    if not metrics.empty:
        lines.append(f"- Date range: {metrics.get('start', pd.Series(dtype=str)).head(1).tolist()} - {metrics.get('end', pd.Series(dtype=str)).tail(1).tolist()}")
    lines.append("")
    # Leaderboard top 20
    lines.append("## Leaderboard (Top 20)")
    if not leaderboard.empty:
        top = leaderboard.head(20)
        # print selected fields
        cols = ["run_id", "score", "Sharpe_p05", "max_drawdown", "n_trades", "fill_rate"]
        # Avoid external deps; render as pipe-separated header + rows
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
        for _, r in top.iterrows():
            lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    else:
        lines.append("No results.")
    lines.append("")
    # Risk warnings
    lines.append("## Risk Warnings")
    warns: List[str] = []
    if not metrics.empty:
        if (metrics["p_value_adj"] > 0.05).any():
            warns.append("Multiple comparisons: many trials not significant after correction.")
        if (metrics["fill_rate"] < 0.5).any():
            warns.append("Low fill rate under assumed capacity constraints.")
        if (metrics["n_trades"] < 5).any():
            warns.append("Sample size small: results unstable.")
    if not warns:
        warns.append("No major warnings triggered by heuristics.")
    for w in warns:
        lines.append(f"- {w}")
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main():  # pragma: no cover
    run_experiment()


if __name__ == "__main__":  # pragma: no cover
    main()
