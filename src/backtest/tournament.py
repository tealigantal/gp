from __future__ import annotations

import argparse
import glob
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml

from .engine import BacktestEngine, CostModel
from .metrics import summarize, equity_max_drawdown
from .experiment import DataCache, _load_yaml, _load_strategy_class_map, _json_hash, daily_returns, sharpe_ratio, cagr_from_equity
from ..providers.local_store import LocalParquetStore


@dataclass
class Candidate:
    name: str
    params: Dict
    file: Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Tournament Runner: realistic vs oracle champion selection")
    p.add_argument("--config", required=True)
    p.add_argument("--strategies", nargs="+", required=True, help="Strategy YAML globs e.g. configs/strategies/*.yaml")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--mode", choices=["realistic", "oracle"], required=True)
    p.add_argument("--training_window", type=int, default=20, help="Training window in trading days")
    p.add_argument("--reselect_interval", choices=["weekly"], default="weekly")
    p.add_argument("--tournament_id", default=None)
    p.add_argument("--emit_registry", help="Path to write champion registry JSON (e.g., store/registry/champion.json)")
    return p.parse_args()


def _collect_dates(store: LocalParquetStore, start: str, end: str, root: Path) -> Tuple[List[str], Dict[str, bool]]:
    # Same as experiment runner
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


def _load_candidates(files: List[Path]) -> List[Candidate]:
    out: List[Candidate] = []
    for fp in files:
        cfg = _load_yaml(fp)
        name = cfg.get("name") or fp.stem
        params = cfg.get("params", {})
        out.append(Candidate(name=name, params=params, file=fp))
    return out


def _evaluate_period(
    candidates: List[Candidate],
    dates: List[str],
    universe_by_date: Dict[str, List[str]],
    basics: pd.DataFrame,
    cost: CostModel,
    root: Path,
) -> Dict[str, Dict]:
    """Run each candidate across the given period and return metrics per candidate.

    Returns: {candidate_key: {"Sharpe": x, "expectancy": y, ...}}
    """
    store = LocalParquetStore(root)
    cache = DataCache(store)
    mp = _load_strategy_class_map()
    metrics: Dict[str, Dict] = {}
    for c in candidates:
        stype = _load_yaml(c.file).get("type")
        StrategyCls = mp.get(stype)
        if not StrategyCls:
            continue
        st = StrategyCls(name=c.name, params=c.params)
        run_dir = root / "results" / "tmp_tournament_eval"
        eng = BacktestEngine([st], initial_cash=1_000_000.0, cost_model=cost, results_dir=run_dir, basics=basics, daily_prev_close={})
        for d in dates:
            uni = universe_by_date.get(d, [])
            # Build min5 and prev map only up to date d
            syms = set(uni)
            syms.update([ts for ts, p in eng.positions.items() if p.shares > 0])
            min5: Dict[str, List[Dict]] = {}
            for ts in sorted(syms):
                df = cache.get_min5(ts, d)
                if df is None or df.empty:
                    continue
                df = df[["trade_time", "open", "high", "low", "close", "vol", "amount"]]
                tup = list(df.itertuples(index=False, name=None))
                bars = [
                    {"trade_time": t[0], "open": float(t[1]), "high": float(t[2]), "low": float(t[3]), "close": float(t[4]), "vol": float(t[5]), "amount": float(t[6])}
                    for t in tup
                ]
                min5[ts] = bars
            prev_map: Dict[str, float] = {}
            for ts in sorted(syms):
                daily = cache.get_daily(ts)
                if daily is None or daily.empty:
                    continue
                prev = daily[daily["trade_date"] < d]
                if prev.empty:
                    continue
                prev_map[ts] = float(prev.iloc[-1]["close"])
            eng.daily_prev_close = prev_map
            eng.run_day(d, min5, uni)
        eng.finalize()
        # Metrics
        eq_path = run_dir / "daily_equity.csv"
        tr_path = run_dir / "trades.csv"
        eq = pd.read_csv(eq_path) if eq_path.exists() else pd.DataFrame()
        tr = pd.read_csv(tr_path) if tr_path.exists() else pd.DataFrame()
        rets = daily_returns(eq["equity"]) if not eq.empty else pd.Series(dtype=float)
        metrics[c.name + ":" + _json_hash(c.params)] = {
            "Sharpe": sharpe_ratio(rets),
            "expectancy": float((tr["price"] * tr["shares"]).mean()) if not tr.empty else 0.0,
        }
    return metrics


def run_tournament():  # pragma: no cover - orchestration heavy
    args = parse_args()
    root = Path.cwd()
    store = LocalParquetStore(root)
    cache = DataCache(store)
    cfg = _load_yaml(Path(args.config))
    basics = store.read_raw("stock_basic")
    if basics is None:
        basics = pd.DataFrame(columns=["ts_code", "name", "market", "exchange", "is_st"])  # allow tests to run
    base_cost = CostModel(
        commission_rate=float(cfg.get("commission_rate", 0.0003)),
        transfer_fee=float(cfg.get("transfer_fee", 0.00002)),
        stamp_duty=float(cfg.get("stamp_duty", 0.001)),
        slippage_bps=float(cfg.get("slippage_bps", 1.0)),
        min_commission=float(cfg.get("min_commission", 5.0)),
    )

    # Candidate strategies
    files: List[Path] = []
    for g in args.strategies:
        files.extend([Path(p) for p in glob.glob(g)])
    candidates = _load_candidates(files)

    # Dates and weekly checkpoints
    dates, week_last_map = _collect_dates(store, args.start, args.end, root)
    checkpoints = [d for d in dates if week_last_map.get(d, False)]

    # Universe per date
    universe_by_date: Dict[str, List[str]] = {}
    for d in dates:
        uni_file = root / "universe" / f"candidate_pool_{d}.csv"
        if uni_file.exists():
            uni_df = pd.read_csv(uni_file)
            universe_by_date[d] = uni_df["ts_code"].tolist()
        else:
            universe_by_date[d] = []

    # OOS equity tracking
    eq_rows: List[Dict] = []
    tr_all: List[pd.DataFrame] = []
    switching_rows: List[Dict] = []
    equity_level = float(cfg.get("initial_cash", 1_000_000.0))

    # Iterate windows
    last_idx = 0
    for cp in checkpoints:
        # find index of cp in dates
        idx = dates.index(cp)
        # Training window dates up to cp inclusive
        train_start = max(0, idx - args.training_window + 1)
        train_period = dates[train_start : idx + 1]
        # Next segment is cp -> next_cp (exclusive of cp for OOS)
        next_cp_idx = checkpoints.index(cp) + 1
        if next_cp_idx < len(checkpoints):
            oos_period = dates[idx + 1 : dates.index(checkpoints[next_cp_idx]) + 1]
        else:
            oos_period = dates[idx + 1 :]

        # Select champion
        # realistic uses training window; oracle uses oos window to select
        if args.mode == "realistic":
            sel_metrics = _evaluate_period(candidates, train_period, universe_by_date, basics, base_cost, root)
            is_oracle = False
        else:
            sel_metrics = _evaluate_period(candidates, oos_period, universe_by_date, basics, base_cost, root)
            is_oracle = True
        # pick best by Sharpe then expectancy
        best_key, best_val = None, None
        for k, v in sel_metrics.items():
            if best_val is None:
                best_key, best_val = k, v
            else:
                if (v.get("Sharpe", 0), v.get("expectancy", 0)) > (best_val.get("Sharpe", 0), best_val.get("expectancy", 0)):
                    best_key, best_val = k, v
        if best_key is None:
            continue

        # Instantiate the chosen strategy for OOS
        name, params_hash = best_key.split(":")
        cand = next(c for c in candidates if c.name == name)
        StrategyCls = _load_strategy_class_map().get(_load_yaml(cand.file).get("type"))
        st = StrategyCls(name=name, params=cand.params)

        # Run OOS segment using fresh engine seeded with current equity level
        run_dir = root / "results" / "tournament_tmp"
        eng = BacktestEngine([st], initial_cash=equity_level, cost_model=base_cost, results_dir=run_dir, basics=basics, daily_prev_close={})
        for d in oos_period:
            uni = universe_by_date.get(d, [])
            # bars and prev map
            syms = set(uni)
            syms.update([ts for ts, p in eng.positions.items() if p.shares > 0])
            min5: Dict[str, List[Dict]] = {}
            for ts in sorted(syms):
                df = cache.get_min5(ts, d)
                if df is None or df.empty:
                    continue
                df = df[["trade_time", "open", "high", "low", "close", "vol", "amount"]]
                tup = list(df.itertuples(index=False, name=None))
                bars = [
                    {"trade_time": t[0], "open": float(t[1]), "high": float(t[2]), "low": float(t[3]), "close": float(t[4]), "vol": float(t[5]), "amount": float(t[6])}
                    for t in tup
                ]
                min5[ts] = bars
            prev_map: Dict[str, float] = {}
            for ts in sorted(syms):
                daily = cache.get_daily(ts)
                if daily is None or daily.empty:
                    continue
                prev = daily[daily["trade_date"] < d]
                if prev.empty:
                    continue
                prev_map[ts] = float(prev.iloc[-1]["close"])
            eng.daily_prev_close = prev_map
            eng.run_day(d, min5, uni)
        eng.finalize()
        eq_path = run_dir / "daily_equity.csv"
        tr_path = run_dir / "trades.csv"
        eq = pd.read_csv(eq_path) if eq_path.exists() else pd.DataFrame()
        tr = pd.read_csv(tr_path) if tr_path.exists() else pd.DataFrame()
        if not eq.empty:
            equity_level = float(eq.iloc[-1]["equity"])
            eq_rows.extend(eq.to_dict(orient="records"))
        if not tr.empty:
            tr_all.append(tr)
        switching_rows.append({
            "decision_date": cp,
            "champion": name,
            "params_hash": params_hash,
            "score_Sharpe": best_val.get("Sharpe", 0.0),
            "score_expectancy": best_val.get("expectancy", 0.0),
            "is_oracle": is_oracle,
            "params": cand.params,
        })

    # Persist outputs
    tid = args.tournament_id or f"{args.mode}_{args.start}_{args.end}"
    out_dir = root / "results" / f"tournament_{tid}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(eq_rows).to_csv(out_dir / "equity.csv", index=False)
    pd.DataFrame(switching_rows).to_csv(out_dir / "switching_log.csv", index=False)

    # OOS metrics
    eq_df = pd.DataFrame(eq_rows)
    tr_df = pd.concat(tr_all, ignore_index=True) if tr_all else pd.DataFrame()
    if not eq_df.empty:
        rets = daily_returns(eq_df["equity"]) if "equity" in eq_df.columns else pd.Series(dtype=float)
        sharpe = sharpe_ratio(rets)
        mdd = equity_max_drawdown(eq_df["equity"]) if "equity" in eq_df.columns else 0.0
        cagr = cagr_from_equity(eq_df["equity"], eq_df.get("trade_date", []))
    else:
        sharpe = mdd = cagr = 0.0
    metrics = {
        "mode": args.mode,
        "is_oracle": (args.mode == "oracle"),
        "CAGR": cagr,
        "Sharpe": sharpe,
        "max_drawdown": mdd,
        "trades": int(len(tr_df)) if not tr_df.empty else 0,
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    # Optionally emit champion registry (freeze last champion)
    if args.emit_registry:
        from .experiment import _get_git_commit, _json_hash
        from ..service.registry import ChampionRecord, write_champion_registry
        selected = switching_rows[-1] if switching_rows else None
        if selected:
            champ_name = selected["champion"]
            cand = next((c for c in candidates if c.name == champ_name), None)
            stype = _load_yaml(cand.file).get("type") if cand else "baseline"
            params = cand.params if cand else {}
            record = ChampionRecord(
                champion_id=args.tournament_id or f"{args.mode}_{args.start}_{args.end}",
                selected_at=selected["decision_date"],
                seed=42,
                git_commit=_get_git_commit(Path.cwd()),
                strategy_type=stype,
                params=params,
                params_hash=_json_hash(params),
                scenario="base",
                robust={
                    "robust_sharpe_p05": 0.0,
                    "worst_year_return": None,
                    "fill_rate": None,
                    "max_drawdown": metrics.get("max_drawdown", 0.0),
                    "n_trades": metrics.get("trades", 0),
                    "p_value_adj": None,
                },
                constraints={
                    "max_participation_rate": None,
                },
                warnings={},
            )
            write_champion_registry(Path(args.emit_registry), record)


def main():  # pragma: no cover
    run_tournament()


if __name__ == "__main__":  # pragma: no cover
    main()
