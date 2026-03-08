from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Avoid global pandas import to make preopen runnable in minimal env
import yaml

from ..backtest.engine import BacktestEngine, CostModel
from ..backtest.runner_weekly import load_strategies
from ..backtest.experiment import _json_hash, _get_git_commit
from ..providers.local_store import LocalParquetStore
from ..gp_assistant.core.paths import store_dir as _store_dir, results_dir as _results_dir, universe_dir as _universe_dir
from .state import LiveState, PositionState
from .output import build_reco_json, write_reco_json
from .risk_engine import ServiceRiskConfig, limit_picks
from .registry import read_champion_registry
from .io_utils import write_json_atomic, copy_atomic
from .lock import FileLock
from .symbols import canonicalize_ts_code


def _load_cfg() -> Dict:
    p = Path("configs/config.yaml")
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _select_topk_from_pool(pool_file: Path, topk: int) -> List[str]:
    """Deprecated: retained only for metrics. Engine no longer uses this pool"""
    if not pool_file.exists():
        return []
    try:
        import pandas as pd  # type: ignore
        df = pd.read_csv(pool_file)
        codes = df["ts_code"].astype(str).tolist()
        return codes[:topk]
    except Exception:
        return []


def _canonical_date(d: str) -> str:
    """Return YYYYMMDD string from YYYYMMDD or YYYY-MM-DD input."""
    s = str(d).strip()
    if len(s) == 8 and s.isdigit():
        return s
    if len(s) == 10 and s[4] == '-' and s[7] == '-':
        return s[0:4] + s[5:7] + s[8:10]
    return s


def service_preopen(date: str, *, topk: int = 10) -> None:
    store_root = _store_dir()
    rec_dir = store_root / "recommend"
    rec_dir.mkdir(parents=True, exist_ok=True)
    lock_path = rec_dir / ".lock"
    date_c = _canonical_date(date)
    # Generate picks via unified engine (default agent)
    try:
        from ..gp_assistant.recommend.engine import run as engine_run
        reco = engine_run(date=date_c, topk=topk)
    except Exception:
        # Fallback minimal object if engine failed; retain legacy structure fields
        reco = {"picks": [], "as_of": date_c, "as_of_ts": f"{date_c} 09:20:00", "debug": {"degraded": True, "degrade_reasons": [{"reason_code": "ENGINE_FAILED"}]}}
    # normalize to v1 shape using service mode normalizer
    try:
        from ..gp_assistant.recommend.modes import service as _svc
        obj = _svc._normalize_to_v1(reco)  # type: ignore[attr-defined]
    except Exception:
        obj = {"picks": reco.get("picks", []), "meta": {"as_of": date_c, "as_of_ts": f"{date_c} 09:20:00", "timezone": "Asia/Shanghai", "tradeable": True, "message": "preopen", "debug": {}}}
    # enforce service stage and timestamps
    if isinstance(obj.get("meta"), dict):
        obj["meta"]["stage"] = "preopen"
        obj["meta"].setdefault("as_of", date_c)
        obj["meta"].setdefault("as_of_ts", f"{date_c} 09:20:00")
    # write per-date and latest with lock + atomic
    with FileLock(lock_path):
        write_reco_json(rec_dir / f"{date_c}.json", obj)
        write_reco_json(rec_dir / "latest.json", obj)


def _run_live_once(date: str) -> Dict:
    """Run a one-shot live backtest for the day using champion strategy.

    Overwrites outputs to be idempotent.
    """
    root = Path.cwd()  # used only for LocalParquetStore root; path usage below uses core.paths
    store = LocalParquetStore(root)
    cfg = _load_cfg()
    import pandas as pd  # local import due to heavy dependency
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
    uni_file = _universe_dir() / f"candidate_pool_{date}.csv"
    universe = []
    if uni_file.exists():
        universe = pd.read_csv(uni_file)["ts_code"].astype(str).tolist()
    # champion
    reg = read_champion_registry(_store_dir() / "registry" / "champion.json") or {}
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
    date_c = _canonical_date(date)
    live_dir = _results_dir() / "live_shadow" / date_c
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
        copy_atomic(src_trades, order_log)
    src_eq = live_dir / "daily_equity.csv"
    if src_eq.exists():
        copy_atomic(src_eq, equity)
    # simple metrics
    trades_df = pd.read_csv(order_log) if order_log.exists() else pd.DataFrame()
    fill_rate = 0.0
    if not trades_df.empty:
        b_exec = int((trades_df["side"] == "BUY").sum())
        b_cxl = int((trades_df["side"] == "CANCEL_BUY").sum())
        b_rj = int((trades_df["side"] == "REJECT_BUY").sum())
        total = b_exec + b_cxl + b_rj
        fill_rate = float(b_exec / total) if total > 0 else 0.0
    metrics = {"date": date_c, "fill_rate": fill_rate, "orders": int(len(trades_df)) if not trades_df.empty else 0}
    write_json_atomic(metrics_path, metrics)
    return metrics


def service_intraday(date: str) -> None:
    _run_live_once(date)
    # Update latest.json
    rec_dir = _store_dir() / "recommend"
    lock_path = rec_dir / ".lock"
    date_c = _canonical_date(date)
    f = rec_dir / f"{date_c}.json"
    if f.exists():
        obj = json.loads(f.read_text(encoding="utf-8"))
        # normalize to v1 shape
        try:
            from ..gp_assistant.recommend.modes import service as _svc

            obj = _svc._normalize_to_v1(obj)  # type: ignore[attr-defined]
        except Exception:
            pass
        if isinstance(obj.get("meta"), dict):
            obj["meta"]["stage"] = "intraday"
            obj["meta"].setdefault("as_of", date_c)
            obj["meta"]["as_of_ts"] = f"{date_c} 14:30:00"
            # enforce empty picks degraded
            if obj.get("meta", {}).get("tradeable", True) and not obj.get("picks"):
                dbg = obj["meta"].setdefault("debug", {})
                dr = list(dbg.get("degrade_reasons") or [])
                dr.append({"reason_code": "EMPTY_PICKS", "detail": {}})
                dbg["degrade_reasons"] = dr
                dbg["degraded"] = True
                dbg["reasons"] = dr
        with FileLock(lock_path):
            write_reco_json(f, obj)
            write_reco_json(rec_dir / "latest.json", obj)


def service_close(date: str) -> None:
    rec_dir = _store_dir() / "recommend"
    lock_path = rec_dir / ".lock"
    date_c = _canonical_date(date)
    f = rec_dir / f"{date_c}.json"
    if f.exists():
        obj = json.loads(f.read_text(encoding="utf-8"))
        try:
            from ..gp_assistant.recommend.modes import service as _svc

            obj = _svc._normalize_to_v1(obj)  # type: ignore[attr-defined]
        except Exception:
            pass
        if isinstance(obj.get("meta"), dict):
            obj["meta"]["stage"] = "close"
            obj["meta"].setdefault("as_of", date_c)
            obj["meta"]["as_of_ts"] = f"{date_c} 15:10:00"
            if obj.get("meta", {}).get("tradeable", True) and not obj.get("picks"):
                dbg = obj["meta"].setdefault("debug", {})
                dr = list(dbg.get("degrade_reasons") or [])
                dr.append({"reason_code": "EMPTY_PICKS", "detail": {}})
                dbg["degrade_reasons"] = dr
                dbg["degraded"] = True
                dbg["reasons"] = dr
        with FileLock(lock_path):
            write_reco_json(f, obj)
            write_reco_json(rec_dir / "latest.json", obj)


def service_publish(date: str) -> None:
    rec_dir = _store_dir() / "recommend"
    lock_path = rec_dir / ".lock"
    date_c = _canonical_date(date)
    src = rec_dir / f"{date_c}.json"
    if src.exists():
        obj = json.loads(src.read_text(encoding="utf-8"))
        try:
            from ..gp_assistant.recommend.modes import service as _svc

            obj = _svc._normalize_to_v1(obj)  # type: ignore[attr-defined]
        except Exception:
            pass
        # ensure meta defaults
        if isinstance(obj.get("meta"), dict):
            obj["meta"].setdefault("stage", obj.get("meta", {}).get("stage") or "intraday")
            obj["meta"].setdefault("as_of", date_c)
            obj["meta"].setdefault("as_of_ts", f"{date_c} 14:30:00")
        with FileLock(lock_path):
            write_reco_json(rec_dir / "latest.json", obj)


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
    # long-running loop
    run = sub.add_parser("run")
    run.add_argument("--date", required=False, help="YYYYMMDD | YYYY-MM-DD | today")
    run.add_argument("--every", type=int, default=300, help="Interval seconds between intraday cycles")
    run.add_argument("--until", type=str, default="15:00", help="Stop at HH:MM local time")
    run.add_argument("--once", action="store_true", default=False, help="Run preopen/intraday/close once for Gate/testing")
    return p.parse_args()


def _service_run(date: Optional[str], every: int, until: str, once: bool = False) -> None:
    """Run the all-day service loop.

    - preopen if missing/expired
    - intraday cycles every `every` seconds
    - close at or after `until`
    - publish after each phase
    """
    from datetime import datetime, time as dtime
    import time

    # resolve date
    if not date or date.strip().lower() == "today":
        date_c = datetime.now().strftime("%Y%m%d")
    else:
        date_c = _canonical_date(date)

    # preopen if not exists
    rec_dir = _store_dir() / "recommend"
    if not (rec_dir / f"{date_c}.json").exists():
        service_preopen(date_c)
        service_publish(date_c)

    def _parse_until(s: str) -> dtime:
        s = (s or "15:00").strip()
        hh, mm = s.split(":")
        return dtime(hour=int(hh), minute=int(mm))

    end_t = _parse_until(until)
    # intraday cycles
    while True:
        now = datetime.now()
        if now.time() >= end_t:
            break
        service_intraday(date_c)
        service_publish(date_c)
        if once:
            break
        time.sleep(max(1, int(every)))

    # close phase
    service_close(date_c)
    service_publish(date_c)


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
    elif args.cmd == "run":
        _service_run(getattr(args, "date", None), int(getattr(args, "every", 300)), str(getattr(args, "until", "15:00")), bool(getattr(args, "once", False)))


if __name__ == "__main__":  # pragma: no cover
    main()
