from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
import json
from pathlib import Path
import time
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


def _fetch_state_path() -> Path:
    return _cache_root() / "fetch_state.json"


def _read_fetch_state() -> Dict[str, Any]:
    p = _fetch_state_path()
    if not p.exists():
        return {"meta": {}, "symbols": {}}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw.setdefault("meta", {})
            raw.setdefault("symbols", {})
            return raw
    except Exception:
        pass
    return {"meta": {}, "symbols": {}}


def _write_fetch_state(state: Dict[str, Any]) -> None:
    _fetch_state_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_state_key(symbol: str, trade_day: str, *, kind: str) -> str:
    return f"{trade_day}:{kind}:{str(symbol).strip()}"


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


def _read_cached_until(symbol: str, trade_day: str, slot_at: str, *, kind: str = "stock") -> pd.DataFrame | None:
    cached = _read_cached_day(symbol, trade_day, kind=kind)
    if cached is None or cached.empty:
        return None
    slot_dt = pd.to_datetime(slot_at)
    scoped = cached[cached["trade_time"] <= slot_dt].reset_index(drop=True)
    return scoped if not scoped.empty else None


def _latest_trade_time(df: pd.DataFrame | None) -> pd.Timestamp | None:
    if df is None or df.empty or "trade_time" not in df.columns:
        return None
    times = pd.to_datetime(df["trade_time"], errors="coerce").dropna()
    if times.empty:
        return None
    return pd.Timestamp(times.max())


def _format_ts(ts: pd.Timestamp | None) -> str | None:
    if ts is None or pd.isna(ts):
        return None
    return pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _symbol_freshness(latest: pd.Timestamp | None, target_dt: pd.Timestamp, *, max_stale_sec: int) -> Dict[str, Any]:
    if latest is None:
        return {
            "source_status": "missing",
            "freshness_state": "missing",
            "effective_slot_at": None,
            "data_age_sec": None,
        }
    age_sec = max(0.0, float((target_dt - latest).total_seconds()))
    if age_sec <= 300.0:
        freshness = "fresh"
    elif age_sec <= float(max_stale_sec):
        freshness = "usable_stale"
    else:
        freshness = "degraded"
    return {
        "source_status": freshness,
        "freshness_state": freshness,
        "effective_slot_at": _format_ts(latest),
        "data_age_sec": age_sec,
    }


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


def _ordered_refresh_items(
    symbols: Iterable[str],
    *,
    benchmark_symbol: str | None,
    core_symbols: Iterable[str] | None,
    core_first: bool,
) -> list[tuple[str, str]]:
    stock_symbols = [str(symbol).strip() for symbol in symbols if str(symbol).strip()]
    core = [str(symbol).strip() for symbol in (core_symbols or []) if str(symbol).strip()]
    items: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(symbol: str, kind: str) -> None:
        key = (str(symbol).strip(), kind)
        if key[0] and key not in seen:
            seen.add(key)
            items.append(key)

    if benchmark_symbol:
        _add(str(benchmark_symbol).strip(), "index")
    if core_first:
        for symbol in core:
            _add(symbol, "stock")
    for symbol in stock_symbols:
        _add(symbol, "stock")
    return items


def refresh_intraday_min5_cache(
    *,
    trading_day: str,
    slot_at: str,
    symbols: Iterable[str],
    benchmark_symbol: str | None = None,
    core_symbols: Iterable[str] | None = None,
    force: bool = False,
) -> Dict[str, Any]:
    cfg = load_config()
    refresh_sec = max(1, int(getattr(cfg, "intraday_min5_refresh_sec", 120) or 120))
    budget_sec = max(1, int(getattr(cfg, "intraday_fetch_budget_sec", 110) or 110))
    cooldown_sec = max(0, int(getattr(cfg, "intraday_symbol_cooldown_sec", 90) or 90))
    core_first = bool(getattr(cfg, "intraday_core_first", True))
    state = _read_fetch_state()
    meta = dict(state.get("meta") or {})
    symbols_state = dict(state.get("symbols") or {})
    target_key = f"{trading_day}:{slot_at}"
    now_epoch = time.time()
    last_attempt = float(meta.get("last_refresh_attempt_at") or 0.0)
    elapsed_since_refresh = now_epoch - last_attempt
    if not force and elapsed_since_refresh < refresh_sec:
        return {
            "skipped": True,
            "reason": "refresh_interval",
            "elapsed_sec": 0.0,
            "next_refresh_after_sec": round(refresh_sec - elapsed_since_refresh, 3),
        }
    started = time.monotonic()
    deadline = started + float(budget_sec)
    start_date = f"{trading_day[:4]}-{trading_day[4:6]}-{trading_day[6:8]} 09:30:00"
    end_date = str(pd.to_datetime(slot_at).strftime("%Y-%m-%d %H:%M:%S"))
    items = _ordered_refresh_items(
        symbols,
        benchmark_symbol=benchmark_symbol,
        core_symbols=core_symbols,
        core_first=core_first,
    )
    report: Dict[str, Any] = {
        "skipped": False,
        "reason": "completed",
        "target_slot_at": slot_at,
        "attempted": [],
        "updated": [],
        "cache_complete": [],
        "cooldown": [],
        "short_circuit": [],
        "failed": [],
        "budget_exhausted": [],
    }
    target_dt = pd.to_datetime(slot_at)
    for symbol, kind in items:
        if time.monotonic() >= deadline:
            report["reason"] = "budget_exhausted"
            report["budget_exhausted"].append({"symbol": symbol, "kind": kind})
            continue
        cached = _read_cached_until(symbol, trading_day, slot_at, kind=kind)
        latest = _latest_trade_time(cached)
        if latest is not None and latest >= target_dt:
            report["cache_complete"].append({"symbol": symbol, "kind": kind, "latest": _format_ts(latest)})
            continue
        key = _fetch_state_key(symbol, trading_day, kind=kind)
        item_state = dict(symbols_state.get(key) or {})
        last_fetch = float(item_state.get("last_fetch_at") or 0.0)
        fail_count = int(item_state.get("fail_count") or 0)
        if not force and fail_count >= 2 and now_epoch - last_fetch < refresh_sec:
            report["short_circuit"].append({"symbol": symbol, "kind": kind, "fail_count": fail_count})
            continue
        if not force and cooldown_sec > 0 and now_epoch - last_fetch < cooldown_sec:
            report["cooldown"].append({"symbol": symbol, "kind": kind})
            continue
        report["attempted"].append({"symbol": symbol, "kind": kind})
        try:
            df = _fetch_cached_or_live(symbol, trading_day, start_date, end_date, kind=kind)
            latest_after = _latest_trade_time(df)
            symbols_state[key] = {
                "last_fetch_at": now_epoch,
                "fail_count": 0,
                "last_error": None,
                "last_success_slot_at": _format_ts(latest_after),
            }
            report["updated"].append({"symbol": symbol, "kind": kind, "latest": _format_ts(latest_after)})
        except Exception as ex:  # noqa: BLE001
            symbols_state[key] = {
                **item_state,
                "last_fetch_at": now_epoch,
                "fail_count": fail_count + 1,
                "last_error": f"{type(ex).__name__}: {ex}",
            }
            report["failed"].append({"symbol": symbol, "kind": kind, "error": f"{type(ex).__name__}: {ex}"})
    meta.update(
        {
            "last_refresh_attempt_at": now_epoch,
            "last_refresh_target": target_key,
            "last_refresh_elapsed_sec": round(time.monotonic() - started, 3),
        }
    )
    state["meta"] = meta
    state["symbols"] = symbols_state
    _write_fetch_state(state)
    report["elapsed_sec"] = round(time.monotonic() - started, 3)
    return report


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

    executor = ThreadPoolExecutor(max_workers=max_workers)
    futures = {executor.submit(_one, sym): sym for sym in syms}
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
    except FuturesTimeoutError as ex_timeout:
        for fut, sym in futures.items():
            if not fut.done():
                fut.cancel()
                errors.setdefault(sym, f"TimeoutError: {ex_timeout}")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    if errors and bool(getattr(cfg, "intraday_fetch_retry_missing", False)):
        retry_symbols = [sym for sym in syms if sym not in out]
        if retry_symbols:
            logger.warning("[min5] retry missing symbols trade_day=%s slot=%s symbols=%s", trading_day, slot_at, retry_symbols)
        for sym in retry_symbols:
            try:
                key, df = _one(sym)
                if not df.empty:
                    out[key] = df
                    errors.pop(sym, None)
                else:
                    errors[sym] = "empty"
            except Exception as ex_item:  # noqa: BLE001
                errors[sym] = f"{type(ex_item).__name__}: {ex_item}"
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
    core_symbols: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    cfg = load_config()
    benchmark_symbol = benchmark_symbol or getattr(cfg, "intraday_benchmark_symbol", "000300")
    max_stale_sec = max(0, int(getattr(cfg, "intraday_model_max_stale_sec", 600) or 600))
    syms = [str(symbol).strip() for symbol in symbols if str(symbol).strip()]
    core = [str(symbol).strip() for symbol in (core_symbols or syms) if str(symbol).strip()]
    target_dt = pd.to_datetime(slot_at)
    bars: Dict[str, pd.DataFrame] = {}
    symbol_statuses: Dict[str, Dict[str, Any]] = {}
    fresh_symbols: list[str] = []
    usable_stale_symbols: list[str] = []
    missing_symbols: list[str] = []
    degraded_symbols: list[str] = []
    latest_by_symbol: Dict[str, pd.Timestamp] = {}
    cache_hits = 0

    for symbol in syms:
        df = _read_cached_until(symbol, trading_day, slot_at, kind="stock")
        latest = _latest_trade_time(df)
        quality = _symbol_freshness(latest, target_dt, max_stale_sec=max_stale_sec)
        quality["target_slot_at"] = slot_at
        symbol_statuses[symbol] = quality
        status = str(quality.get("freshness_state") or "missing")
        if latest is not None:
            cache_hits += 1
            latest_by_symbol[symbol] = latest
        if status == "fresh":
            fresh_symbols.append(symbol)
            bars[symbol] = df if df is not None else pd.DataFrame()
        elif status == "usable_stale":
            usable_stale_symbols.append(symbol)
            bars[symbol] = df if df is not None else pd.DataFrame()
        elif status == "degraded":
            degraded_symbols.append(symbol)
        else:
            missing_symbols.append(symbol)

    benchmark = _read_cached_until(benchmark_symbol, trading_day, slot_at, kind="index")
    benchmark_latest = _latest_trade_time(benchmark)
    benchmark_quality = _symbol_freshness(benchmark_latest, target_dt, max_stale_sec=max_stale_sec)
    benchmark_quality["target_slot_at"] = slot_at
    benchmark_received = str(benchmark_quality.get("freshness_state") or "missing") in {"fresh", "usable_stale"}
    if benchmark_received and benchmark is not None:
        cache_hits += 1
    else:
        benchmark = None

    required_latest: list[pd.Timestamp] = []
    required_symbols = [symbol for symbol in core if symbol in syms]
    core_missing = [symbol for symbol in required_symbols if symbol not in bars]
    for symbol in required_symbols:
        if symbol in latest_by_symbol and symbol in bars:
            required_latest.append(latest_by_symbol[symbol])
    if benchmark_latest is not None and benchmark_received:
        required_latest.append(benchmark_latest)
    effective_ts = min(required_latest) if required_latest and not core_missing and benchmark_received else (max(latest_by_symbol.values()) if latest_by_symbol else None)
    effective_slot_at = _format_ts(effective_ts)
    if effective_ts is not None:
        refreshed_bars: Dict[str, pd.DataFrame] = {}
        fresh_symbols = []
        usable_stale_symbols = []
        missing_symbols = []
        degraded_symbols = []
        for symbol, df in list(bars.items()):
            scoped = df[df["trade_time"] <= effective_ts].reset_index(drop=True)
            latest = _latest_trade_time(scoped)
            quality = _symbol_freshness(latest, target_dt, max_stale_sec=max_stale_sec)
            quality["target_slot_at"] = slot_at
            symbol_statuses[symbol] = quality
            status = str(quality.get("freshness_state") or "missing")
            if status == "fresh":
                fresh_symbols.append(symbol)
                refreshed_bars[symbol] = scoped
            elif status == "usable_stale":
                usable_stale_symbols.append(symbol)
                refreshed_bars[symbol] = scoped
            elif status == "degraded":
                degraded_symbols.append(symbol)
            else:
                missing_symbols.append(symbol)
        for symbol in syms:
            if symbol not in symbol_statuses or symbol in refreshed_bars:
                continue
            status = str(symbol_statuses[symbol].get("freshness_state") or "missing")
            if status == "degraded" and symbol not in degraded_symbols:
                degraded_symbols.append(symbol)
            elif status == "missing" and symbol not in missing_symbols:
                missing_symbols.append(symbol)
        bars = refreshed_bars
        if benchmark is not None:
            benchmark = benchmark[benchmark["trade_time"] <= effective_ts].reset_index(drop=True)
            benchmark_quality = _symbol_freshness(_latest_trade_time(benchmark), target_dt, max_stale_sec=max_stale_sec)
            benchmark_quality["target_slot_at"] = slot_at
            benchmark_received = str(benchmark_quality.get("freshness_state") or "missing") in {"fresh", "usable_stale"}
            if not benchmark_received:
                benchmark = None
    core_missing = [symbol for symbol in required_symbols if symbol not in bars]
    model_usable = bool(benchmark_received and not core_missing and effective_ts is not None)
    effective_age_sec = None if effective_ts is None else max(0.0, float((target_dt - effective_ts).total_seconds()))
    if not model_usable:
        freshness_state = "degraded"
    elif any(symbol in usable_stale_symbols for symbol in required_symbols) or str(benchmark_quality.get("freshness_state")) == "usable_stale":
        freshness_state = "usable_stale"
    else:
        freshness_state = "fresh"

    errors: list[str] = []
    if core_missing:
        errors.append(f"core_symbols_missing:{','.join(sorted(core_missing))}")
    if not benchmark_received:
        errors.append(f"benchmark_missing:{benchmark_symbol}")
    if model_usable and freshness_state == "degraded":
        errors.append("data_too_stale")

    snapshot = build_slot_breadth_snapshot(bars, slot_at=effective_slot_at or slot_at)
    snapshot_age_sec: Optional[float] = None
    if snapshot is not None and not snapshot.empty:
        snapshot_age_sec = 0.0
    if snapshot is None or snapshot.empty:
        errors.append("snapshot_missing")
        model_usable = False
        freshness_state = "degraded"
    return {
        "bars": bars,
        "benchmark": benchmark,
        "benchmark_symbol": benchmark_symbol,
        "benchmark_status": benchmark_quality,
        "snapshot": snapshot,
        "requested_slot_at": slot_at,
        "target_slot_at": slot_at,
        "effective_slot_at": effective_slot_at,
        "freshness_state": freshness_state,
        "data_age_sec": effective_age_sec,
        "provider": "akshare",
        "errors": errors,
        "snapshot_age_sec": snapshot_age_sec,
        "symbol_statuses": symbol_statuses,
        "fresh_symbols": fresh_symbols,
        "usable_stale_symbols": usable_stale_symbols,
        "missing_symbols": sorted(set(missing_symbols + degraded_symbols)),
        "model_usable": bool(model_usable),
        "symbols_expected": len(syms),
        "symbols_received": len(bars),
        "benchmark_received": bool(benchmark_received and benchmark is not None and not benchmark.empty),
        "cache_hit_rate": float(cache_hits / max(1, len(syms) + 1)),
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
