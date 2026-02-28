from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yaml

from ..backtest.engine import BacktestEngine, CostModel
from ..backtest.runner_weekly import load_strategies
from ..backtest.experiment import _json_hash, _get_git_commit
from ..providers.local_store import LocalParquetStore
from .state import LiveState, PositionState
from .output import build_reco_json, write_reco_json
from .risk_engine import ServiceRiskConfig, limit_picks
from .registry import read_champion_registry


def _load_cfg() -> Dict:
    p = Path("configs/config.yaml")
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _select_topk_from_pool(pool_file: Path, topk: int) -> List[str]:
    if not pool_file.exists():
        return []
    df = pd.read_csv(pool_file)
    codes = df["ts_code"].astype(str).tolist()
    return codes[:topk]


def service_preopen(date: str, *, topk: int = 10) -> None:
    root = Path.cwd()
    store_dir = root / "store"
    rec_dir = store_dir / "recommend"
    rec_dir.mkdir(parents=True, exist_ok=True)
    # ensure candidate pool
    uni_file = root / "universe" / f"candidate_pool_{date}.csv"
    if not uni_file.exists():
        try:
            from .. import gp_assistant  # noqa: F401
        except Exception:
            pass
        # best-effort: don't fail if cannot build
    # pick champion from registry
    reg = read_champion_registry(store_dir / "registry" / "champion.json") or {}
    champ = {
        "strategy": reg.get("strategy_type", "baseline"),
        "score": reg.get("robust", {}).get("robust_sharpe_p05", 0.0),
        "params_hash": reg.get("params_hash", ""),
        "scenario": reg.get("scenario", "base"),
    }
    # top picks
    cfg = _load_cfg()
    risk_cfg = ServiceRiskConfig(max_positions=int(cfg.get("max_positions", 10)))
    picks_codes = limit_picks(_select_topk_from_pool(uni_file, topk), risk_cfg)
    picks = [
        {
            "symbol": code,
            "name": "",
            "theme": "",
            "champion": champ,
            "trade_plan": {"entry": 0.0, "stop": 0.0, "take": 0.0, "bands": {}, "actions": {}},
            "tags": [],
            "risk": {"max_position": 1.0 / max(1, risk_cfg.max_positions), "cooldown": risk_cfg.cooldown_days},
            "debug": {},
        }
        for code in picks_codes
    ]
    as_of = f"{date} 09:20:00"
    obj = build_reco_json(as_of=as_of, stage="preopen", picks=picks, tradeable=True, message="preopen")
    # write per-date and latest
    write_reco_json(rec_dir / f"{date}.json", obj)
    write_reco_json(rec_dir / "latest.json", obj)


def _run_live_once(date: str) -> Dict:
    """Run a one-shot live backtest for the day using champion strategy.

    Overwrites outputs to be idempotent.
    """
    root = Path.cwd()
    store = LocalParquetStore(root)
    cfg = _load_cfg()
    basics = store.read_raw("stock_basic")
    if basics is None:
        basics = pd.DataFrame(columns=["ts_code", "name", "market", "exchange", "is_st"])  # tolerable
    cost = CostModel(
        commission_rate=float(cfg.get("commission_rate", 0.0003)),
        transfer_fee=float(cfg.get("transfer_fee", 0.00002)),
        stamp_duty=float(cfg.get("stamp_duty", 0.001)),
        slippage_bps=float(cfg.get("slippage_bps", 1.0)),
        min_commission=float(cfg.get("min_commission", 5.0)),
    )
    # read pool
    uni_file = root / "universe" / f"candidate_pool_{date}.csv"
    universe = []
    if uni_file.exists():
        universe = pd.read_csv(uni_file)["ts_code"].astype(str).tolist()
    # champion
    reg = read_champion_registry(root / "store" / "registry" / "champion.json") or {}
    stype = reg.get("strategy_type", "baseline")
    params = reg.get("params", {"entry_time": "09:50:00", "topk": 1, "lot_shares": 100})
    # load one strategy by mapping file types
    from ..backtest.experiment import _load_strategy_class_map
    StrategyCls = _load_strategy_class_map().get(stype)
    if StrategyCls is None:
        # fallback to baseline
        StrategyCls = _load_strategy_class_map()["baseline"]
        stype = "baseline"
    st = StrategyCls(name=f"live_{stype}", params=params)
    # Engine
    live_dir = root / "results" / "live_shadow" / date
    eng = BacktestEngine([st], initial_cash=float(cfg.get("initial_cash", 1_000_000.0)), cost_model=cost, results_dir=live_dir, basics=basics, daily_prev_close={})
    if "max_participation_rate" in cfg:
        try:
            eng.max_participation_rate = float(cfg.get("max_participation_rate"))
        except Exception:
            pass
    # Build min5 map and prev close
    min5: Dict[str, List[Dict]] = {}
    for ts in universe:
        df = store.read_min5(ts, date)
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
    for ts in universe:
        daily = store.read_daily(ts, end=date)
        if daily is None or daily.empty:
            continue
        prev = daily[daily["trade_date"] < date]
        if prev.empty:
            continue
        prev_map[ts] = float(prev.iloc[-1]["close"])
    eng.daily_prev_close = prev_map
    # Execute once
    eng.run_day(date, min5, universe)
    eng.finalize()
    # Rename engine outputs for live
    live_dir.mkdir(parents=True, exist_ok=True)
    # Convert engine trades/equity to expected filenames
    order_log = live_dir / "order_log.csv"
    equity = live_dir / "equity.csv"
    metrics_path = live_dir / "metrics.json"
    # copy
    import shutil
    src_trades = live_dir / "trades.csv"
    if src_trades.exists():
        shutil.copyfile(src_trades, order_log)
    src_eq = live_dir / "daily_equity.csv"
    if src_eq.exists():
        shutil.copyfile(src_eq, equity)
    # simple metrics
    trades_df = pd.read_csv(order_log) if order_log.exists() else pd.DataFrame()
    fill_rate = 0.0
    if not trades_df.empty:
        b_exec = int((trades_df["side"] == "BUY").sum())
        b_cxl = int((trades_df["side"] == "CANCEL_BUY").sum())
        b_rj = int((trades_df["side"] == "REJECT_BUY").sum())
        total = b_exec + b_cxl + b_rj
        fill_rate = float(b_exec / total) if total > 0 else 0.0
    metrics = {"date": date, "fill_rate": fill_rate, "orders": int(len(trades_df)) if not trades_df.empty else 0}
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics


def service_intraday(date: str) -> None:
    _run_live_once(date)
    # Update latest.json
    root = Path.cwd()
    rec_dir = root / "store" / "recommend"
    if (rec_dir / f"{date}.json").exists():
        obj = json.loads((rec_dir / f"{date}.json").read_text(encoding="utf-8"))
        obj["stage"] = "intraday"
        obj["as_of"] = f"{date} 14:30:00"
        write_reco_json(rec_dir / f"{date}.json", obj)
        write_reco_json(rec_dir / "latest.json", obj)


def service_close(date: str) -> None:
    root = Path.cwd()
    rec_dir = root / "store" / "recommend"
    f = rec_dir / f"{date}.json"
    if f.exists():
        obj = json.loads(f.read_text(encoding="utf-8"))
        obj["stage"] = "close"
        obj["as_of"] = f"{date} 15:10:00"
        write_reco_json(f, obj)
        write_reco_json(rec_dir / "latest.json", obj)


def service_publish(date: str) -> None:
    root = Path.cwd()
    rec_dir = root / "store" / "recommend"
    src = rec_dir / f"{date}.json"
    if src.exists():
        write_reco_json(rec_dir / "latest.json", json.loads(src.read_text(encoding="utf-8")))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Service pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    pre = sub.add_parser("preopen")
    pre.add_argument("--date", required=True)
    pre.add_argument("--topk", type=int, default=10)
    intra = sub.add_parser("intraday")
    intra.add_argument("--date", required=True)
    intra.add_argument("--once", action="store_true", default=True)
    close = sub.add_parser("close")
    close.add_argument("--date", required=True)
    pub = sub.add_parser("publish")
    pub.add_argument("--date", required=True)
    return p.parse_args()


def main():  # pragma: no cover
    args = parse_args()
    if args.cmd == "preopen":
        service_preopen(args.date, topk=args.topk)
    elif args.cmd == "intraday":
        service_intraday(args.date)
    elif args.cmd == "close":
        service_close(args.date)
    elif args.cmd == "publish":
        service_publish(args.date)


if __name__ == "__main__":  # pragma: no cover
    main()

