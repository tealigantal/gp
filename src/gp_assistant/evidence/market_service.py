from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pandas as pd

from ..core.config import load_config
from ..core.logging import logger
from ..core.paths import data_dir
from ..providers.factory import get_provider
from ..runtime.market_clock import compute_market_state
from ..selection_engine.agent import run as run_selection
from ..selection_engine.datahub import MarketDataHub
from .daily_freshness import reconcile_daily_freshness, selection_symbols


def current_trading_day() -> str:
    return str(compute_market_state().target_daybook_effective_day)


def build_day_selection(trading_day: str, *, topk: int = 10, risk_profile: str = "normal") -> Dict[str, Any]:
    date = f"{trading_day[:4]}-{trading_day[4:6]}-{trading_day[6:8]}" if len(trading_day) == 8 else trading_day
    raw = run_selection(date=date, topk=topk, universe="auto", risk_profile=risk_profile)
    report = reconcile_daily_freshness(selection_symbols(raw), as_of=date, strict=True)
    if report["refreshed_symbols"]:
        raw = run_selection(date=date, topk=topk, universe="auto", risk_profile=risk_profile)
        report = reconcile_daily_freshness(selection_symbols(raw), as_of=date, strict=True)
    report_map = {item["symbol"]: item for item in report["symbol_reports"]}
    for bucket in ("picks", "candidate_pool"):
        for item in raw.get(bucket) or []:
            symbol = str(item.get("symbol") or item.get("code") or "").strip()
            if not symbol or symbol not in report_map:
                continue
            item["daily_freshness_state"] = report_map[symbol].get("freshness_state")
            item["last_date"] = report_map[symbol].get("last_item_time") or item.get("last_date")
    raw["daily_freshness"] = report
    if report["ready"]:
        return raw
    debug = dict(raw.get("debug") or {})
    degrade_reasons = list(debug.get("degrade_reasons") or [])
    degrade_reasons.append(
        {
            "reason_code": "DAILY_FRESHNESS_BLOCKED",
            "target_day": report["target_day"],
            "stale_symbols": report["stale_symbols"][:10],
            "failed_symbols": report["failed_symbols"][:10],
        }
    )
    debug["degraded"] = True
    debug["degrade_reasons"] = degrade_reasons
    return {
        **raw,
        "candidate_pool": [],
        "picks": [],
        "tradeable": False,
        "reason": "daily_freshness_blocked",
        "message": report["blocking_reason"],
        "daily_freshness": report,
        "debug": debug,
    }


def fetch_snapshot() -> pd.DataFrame | None:
    provider = get_provider()
    try:
        snapshot = provider.get_spot_snapshot()
        meta = getattr(provider, "last_snapshot_meta", lambda: {})() or {}
        if not isinstance(snapshot, pd.DataFrame) or snapshot.empty:
            return None
        source = str(meta.get("source") or "").strip().lower()
        cache = str(meta.get("cache") or "").strip().lower()
        cache_of = str(meta.get("cache_of") or "").strip().lower()
        if meta.get("missing") or meta.get("stale") or meta.get("fallback"):
            logger.warning("[snapshot] fail-closed meta=%s", meta)
            return None
        if cache == "file":
            logger.warning("[snapshot] reject file cache as current snapshot meta=%s", meta)
            return None
        if cache == "memory" and not cache_of:
            logger.warning("[snapshot] reject memory cache without live provenance meta=%s", meta)
            return None
        if not source and not cache_of:
            logger.warning("[snapshot] reject snapshot without source provenance meta=%s", meta)
            return None
        return snapshot
    except Exception:
        return None


def build_slot_breadth_snapshot(
    bars_by_symbol: Dict[str, pd.DataFrame],
    *,
    slot_at: str,
) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    slot_dt = pd.to_datetime(slot_at)
    for symbol, df in bars_by_symbol.items():
        if df is None or df.empty:
            continue
        scoped = df[df["trade_time"] <= slot_dt].reset_index(drop=True)
        if scoped.empty:
            continue
        first_open = float(pd.to_numeric(scoped["open"].iloc[0], errors="coerce") or 0.0)
        last_close = float(pd.to_numeric(scoped["close"].iloc[-1], errors="coerce") or 0.0)
        last_open = float(pd.to_numeric(scoped["open"].iloc[-1], errors="coerce") or 0.0)
        last_high = float(pd.to_numeric(scoped["high"].iloc[-1], errors="coerce") or 0.0)
        last_low = float(pd.to_numeric(scoped["low"].iloc[-1], errors="coerce") or 0.0)
        volume = float(pd.to_numeric(scoped["vol"], errors="coerce").fillna(0.0).sum())
        if first_open <= 0 or last_close <= 0:
            continue
        pct_chg = (last_close / first_open - 1.0) * 100.0
        rows.append(
            {
                "symbol": symbol,
                "pct_chg": pct_chg,
                "chg": pct_chg,
                "open": first_open,
                "last": last_close,
                "close": last_close,
                "bar_open": last_open,
                "bar_high": last_high,
                "bar_low": last_low,
                "volume": volume,
                "ts": slot_dt,
            }
        )
    return pd.DataFrame(rows)


def _cache_root() -> Path:
    p = data_dir() / "cache" / "min5"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _baseline_root() -> Path:
    p = data_dir() / "cache" / "min5_baseline"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _trade_day_path(trade_day: str) -> Path:
    p = _cache_root() / f"trade_day={trade_day}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _cache_symbol_name(symbol: str, *, kind: str) -> str:
    return f"{kind}_{str(symbol).strip()}" if kind != "stock" else str(symbol).strip()


def _cache_path(symbol: str, trade_day: str, *, kind: str = "stock") -> Path:
    return _trade_day_path(trade_day) / f"symbol={_cache_symbol_name(symbol, kind=kind)}.parquet"


def _baseline_path(symbol: str, trade_day: str) -> Path:
    p = _baseline_root() / f"trade_day={trade_day}"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"symbol={str(symbol).strip()}.parquet"


def _read_cached_day(symbol: str, trade_day: str, *, kind: str = "stock") -> pd.DataFrame | None:
    p = _cache_path(symbol, trade_day, kind=kind)
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
        if "trade_time" not in df.columns:
            return None
        df = df.copy()
        df["trade_time"] = pd.to_datetime(df["trade_time"], errors="coerce")
        return df.dropna(subset=["trade_time"]).sort_values("trade_time").reset_index(drop=True)
    except Exception:
        return None


def _write_cached_day(symbol: str, trade_day: str, df: pd.DataFrame, *, kind: str = "stock") -> None:
    if df.empty:
        return
    out = df.copy()
    out["trade_time"] = pd.to_datetime(out["trade_time"], errors="coerce")
    out = out.dropna(subset=["trade_time"]).sort_values("trade_time").drop_duplicates(subset=["trade_time"], keep="last").reset_index(drop=True)
    out.to_parquet(_cache_path(symbol, trade_day, kind=kind), index=False)


def _merge_day_frames(left: pd.DataFrame | None, right: pd.DataFrame | None) -> pd.DataFrame:
    parts = [frame for frame in [left, right] if isinstance(frame, pd.DataFrame) and not frame.empty]
    if not parts:
        return pd.DataFrame(columns=["trade_time", "open", "high", "low", "close", "vol", "amount"])
    out = pd.concat(parts, ignore_index=True)
    out["trade_time"] = pd.to_datetime(out["trade_time"], errors="coerce")
    return out.dropna(subset=["trade_time"]).sort_values("trade_time").drop_duplicates(subset=["trade_time"], keep="last").reset_index(drop=True)


def _provider_minute_bars(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    provider = get_provider(prefer="akshare")
    return provider.get_minute_bars_5m(symbol, start_date, end_date)


def _provider_index_bars(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    provider = get_provider(prefer="akshare")
    return provider.get_index_minute_bars_5m(symbol, start_date, end_date)


def _fetch_cached_or_live(symbol: str, trading_day: str, start_date: str, end_date: str, *, kind: str) -> pd.DataFrame:
    cached = _read_cached_day(symbol, trading_day, kind=kind)
    end_dt = pd.to_datetime(end_date)
    if cached is not None and not cached.empty:
        cached = cached[cached["trade_time"] <= end_dt].reset_index(drop=True)
        if not cached.empty and cached["trade_time"].max() >= end_dt:
            return cached
    live = _provider_minute_bars(symbol, start_date, end_date) if kind == "stock" else _provider_index_bars(symbol, start_date, end_date)
    live = live[(live["trade_time"] >= pd.to_datetime(start_date)) & (live["trade_time"] <= end_dt)].reset_index(drop=True)
    merged = _merge_day_frames(cached, live)
    if trading_day:
        _write_cached_day(symbol, trading_day, merged, kind=kind)
    return merged


def fetch_minute_bars_5m(symbols: Iterable[str], trading_day: str, *, slot_at: str) -> Dict[str, pd.DataFrame]:
    cfg = load_config()
    syms = [str(symbol).strip() for symbol in symbols if str(symbol).strip()]
    if not syms:
        return {}
    start_date = f"{trading_day[:4]}-{trading_day[4:6]}-{trading_day[6:8]} 09:30:00"
    end_date = str(pd.to_datetime(slot_at).strftime("%Y-%m-%d %H:%M:%S"))
    out: Dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    max_workers = max(1, int(getattr(cfg, "intraday_fetch_workers", 6) or 6))
    timeout_sec = max(5, int(getattr(cfg, "intraday_fetch_timeout_sec", 20) or 20))

    def _one(sym: str) -> tuple[str, pd.DataFrame]:
        return sym, _fetch_cached_or_live(sym, trading_day, start_date, end_date, kind="stock")

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_one, sym): sym for sym in syms}
        try:
            for fut in as_completed(futures, timeout=timeout_sec):
                sym = futures[fut]
                try:
                    key, df = fut.result(timeout=0)
                    if not df.empty:
                        out[key] = df
                    else:
                        errors[sym] = "empty"
                except Exception as ex_item:  # noqa: BLE001
                    errors[sym] = f"{type(ex_item).__name__}: {ex_item}"
        except Exception as ex_timeout:  # noqa: BLE001
            for sym in syms:
                errors.setdefault(sym, f"{type(ex_timeout).__name__}: {ex_timeout}")
    if errors:
        logger.warning("[min5] partial failure trade_day=%s slot=%s errors=%s", trading_day, slot_at, errors)
    return out


def fetch_benchmark_bars_5m(symbol: str, trading_day: str, *, slot_at: str) -> pd.DataFrame:
    start_date = f"{trading_day[:4]}-{trading_day[4:6]}-{trading_day[6:8]} 09:30:00"
    end_date = str(pd.to_datetime(slot_at).strftime("%Y-%m-%d %H:%M:%S"))
    return _fetch_cached_or_live(symbol, trading_day, start_date, end_date, kind="index")


def fetch_intraday_bundle(
    *,
    trading_day: str,
    slot_at: str,
    symbols: Iterable[str],
    benchmark_symbol: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = load_config()
    benchmark_symbol = benchmark_symbol or getattr(cfg, "intraday_benchmark_symbol", "000300")
    syms = [str(symbol).strip() for symbol in symbols if str(symbol).strip()]
    bars = fetch_minute_bars_5m(syms, trading_day, slot_at=slot_at)
    benchmark = None
    benchmark_error = None
    try:
        benchmark = fetch_benchmark_bars_5m(benchmark_symbol, trading_day, slot_at=slot_at)
    except Exception as ex:  # noqa: BLE001
        benchmark_error = f"{type(ex).__name__}: {ex}"
        logger.warning("[min5] benchmark failure symbol=%s trade_day=%s slot=%s error=%s", benchmark_symbol, trading_day, slot_at, benchmark_error)
    snapshot = fetch_snapshot()
    snapshot_age_sec: Optional[float] = None
    if snapshot is not None and not snapshot.empty:
        try:
            if "ts" in snapshot.columns and not snapshot["ts"].isna().all():
                ts_value = pd.to_datetime(snapshot["ts"].dropna().iloc[-1])
                snapshot_age_sec = float((pd.Timestamp.now(tz=ts_value.tz) - ts_value).total_seconds())
            else:
                snapshot_age_sec = 0.0
        except Exception:
            snapshot_age_sec = 0.0
    errors: list[str] = []
    if len(bars) != len(syms):
        missing = sorted(set(syms) - set(bars))
        errors.append(f"symbols_missing:{','.join(missing)}")
    if benchmark is None or benchmark.empty:
        errors.append(f"benchmark_missing:{benchmark_symbol}")
    if snapshot is None or snapshot.empty:
        errors.append("snapshot_missing")
    return {
        "bars": bars,
        "benchmark": benchmark,
        "benchmark_symbol": benchmark_symbol,
        "snapshot": snapshot,
        "requested_slot_at": slot_at,
        "provider": "akshare",
        "errors": errors + ([benchmark_error] if benchmark_error else []),
        "snapshot_age_sec": snapshot_age_sec,
        "symbols_expected": len(syms),
        "symbols_received": len(bars),
        "benchmark_received": bool(benchmark is not None and not benchmark.empty),
    }


def _load_baseline_cache(symbol: str, trade_day: str) -> Dict[str, float]:
    p = _baseline_path(symbol, trade_day)
    if not p.exists():
        return {}
    try:
        df = pd.read_parquet(p)
    except Exception:
        return {}
    if df.empty or not {"slot_key", "baseline_vol"} <= set(df.columns):
        return {}
    return {str(row["slot_key"]): float(row["baseline_vol"]) for _, row in df.iterrows() if pd.notna(row["baseline_vol"])}


def load_slot_volume_baselines(trade_day: str, symbols: Iterable[str], *, lookback_days: Optional[int] = None) -> Dict[str, Dict[str, float]]:
    cfg = load_config()
    lookback_days = int(lookback_days or getattr(cfg, "intraday_slot_baseline_days", 20) or 20)
    out: Dict[str, Dict[str, float]] = {}
    start_window = (pd.to_datetime(trade_day) - pd.Timedelta(days=max(40, lookback_days * 2))).strftime("%Y-%m-%d 09:30:00")
    end_window = (pd.to_datetime(trade_day) - pd.Timedelta(days=1)).strftime("%Y-%m-%d 15:00:00")
    for sym in [str(symbol).strip() for symbol in symbols if str(symbol).strip()]:
        cached = _load_baseline_cache(sym, trade_day)
        if cached:
            out[sym] = cached
            continue
        try:
            hist = _provider_minute_bars(sym, start_window, end_window)
        except Exception as ex:  # noqa: BLE001
            logger.warning("[slot-baseline] symbol=%s trade_day=%s error=%s", sym, trade_day, ex)
            out[sym] = {}
            continue
        if hist.empty:
            out[sym] = {}
            continue
        hist = hist.copy()
        hist["trade_time"] = pd.to_datetime(hist["trade_time"], errors="coerce")
        hist = hist.dropna(subset=["trade_time"]).sort_values("trade_time").reset_index(drop=True)
        hist["trade_day"] = hist["trade_time"].dt.strftime("%Y%m%d")
        hist = hist[hist["trade_day"] < trade_day]
        if hist.empty:
            out[sym] = {}
            continue
        hist["slot_key"] = hist["trade_time"].dt.strftime("%H:%M")
        baseline_rows: list[dict[str, Any]] = []
        baseline: Dict[str, float] = {}
        for slot_key, group in hist.groupby("slot_key"):
            recent_days = list(dict.fromkeys(group["trade_day"].tolist()))[-lookback_days:]
            sample = group[group["trade_day"].isin(recent_days)]
            if sample.empty:
                continue
            baseline_val = float(pd.to_numeric(sample["vol"], errors="coerce").dropna().median())
            if baseline_val <= 0:
                continue
            baseline[slot_key] = baseline_val
            baseline_rows.append({"slot_key": slot_key, "baseline_vol": baseline_val, "sample_days": len(recent_days)})
        if baseline_rows:
            pd.DataFrame(baseline_rows).sort_values("slot_key").to_parquet(_baseline_path(sym, trade_day), index=False)
        out[sym] = baseline
    return out


def probe_daybook_ready(target_day: str) -> dict:
    hub = MarketDataHub()
    symbols = ["000001", "600000", "600519"]
    ok = 0
    checks: list[dict] = []
    for symbol in symbols:
        try:
            df, _ = hub.daily_ohlcv(symbol, as_of=target_day)
            last = None
            if df is not None and len(df) > 0 and "date" in df.columns:
                last = str(pd.to_datetime(df.iloc[-1]["date"]).strftime("%Y%m%d"))
            ready = last == target_day
            ok += 1 if ready else 0
            checks.append({"symbol": symbol, "last": last, "ready": ready, "len": int(len(df) if df is not None else 0)})
        except Exception as ex:  # noqa: BLE001
            checks.append({"symbol": symbol, "error": str(ex)})
    return {"ready": ok >= 2, "ok_count": ok, "target_day": target_day, "checks": checks}
