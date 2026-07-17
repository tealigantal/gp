from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from ..core.paths import store_dir
from ..runtime.market_clock import (
    PHASE_CLOSING_AUCTION,
    PHASE_INTRADAY_AM,
    PHASE_INTRADAY_PM,
    PHASE_LUNCH_BREAK,
    PHASE_NON_TRADING,
    PHASE_OPEN_NO_FIRST_BAR,
    PHASE_POSTCLOSE_PENDING,
    PHASE_PREOPEN,
    compute_market_state,
    _last_open_day_on_or_before,
    _load_calendar_df,
    resolve_trading_day_on_or_before,
)
from ..runtime.market_time import MarketTimeContext, iso_day
from ..runtime.utils import now_iso
from ..search.history_store import canonical_query_id, ensure_query, history_db_path, list_queries, query_meta
from ..selection_engine.datahub import MarketDataHub


TARGET_PREVIOUS_COMPLETED = "previous_completed"
TARGET_CURRENT_READY = "current_ready"
TARGET_CURRENT_PENDING = "current_pending"

_UNFINISHED_CURRENT_DAY_PHASES = {
    PHASE_PREOPEN,
    PHASE_OPEN_NO_FIRST_BAR,
    PHASE_INTRADAY_AM,
    PHASE_LUNCH_BREAK,
    PHASE_INTRADAY_PM,
    PHASE_CLOSING_AUCTION,
}
_EOD_PROBE_SYMBOLS = ("000001", "600000", "600519")


def _history_db_path() -> Path:
    return history_db_path()


def _report_path() -> Path:
    path = store_dir() / "cache" / "runtime" / "daily_freshness.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _eod_probe_path() -> Path:
    path = store_dir() / "cache" / "runtime" / "eod_daily_probe.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_latest_daily_freshness_report() -> dict[str, Any] | None:
    path = _report_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_daily_freshness_report(report: dict[str, Any]) -> None:
    _report_path().write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _date_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return pd.to_datetime(value).date().isoformat()
    except Exception:
        s = str(value).strip()
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) >= 8:
            return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return None


def _date_ymd(value: Any) -> str | None:
    iso = _date_iso(value)
    return iso.replace("-", "") if iso else None


def _iso_from_ymd(ymd: str) -> str:
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


def _previous_open_day_ymd(ymd: str) -> str:
    base = pd.to_datetime(_iso_from_ymd(ymd)).normalize()
    cal_df = _load_calendar_df()
    prev = _last_open_day_on_or_before(base - pd.Timedelta(days=1), cal_df)
    return prev.strftime("%Y%m%d")


def _calendar_blocking_reason(status: str | None, start: str | None, end: str | None) -> str | None:
    normalized = str(status or "").strip().lower()
    if normalized in {"", "ok", "unknown"}:
        return None
    if normalized == "missing":
        return "交易日历缺失，请先刷新 data/raw/trade_calendar.parquet。"
    if normalized == "invalid":
        return "交易日历格式无效，请重新生成 data/raw/trade_calendar.parquet。"
    if normalized == "out_of_range":
        if start and end:
            return f"交易日历未覆盖当前日期（当前覆盖 {start} 至 {end}），请先刷新 data/raw/trade_calendar.parquet。"
        return "交易日历未覆盖当前日期，请先刷新 data/raw/trade_calendar.parquet。"
    return f"交易日历不可用（{normalized}），请先刷新 data/raw/trade_calendar.parquet。"


def _freshness_state(last_item_time: Any, target_iso: str) -> str:
    lit = _date_iso(last_item_time)
    if not lit:
        return "missing"
    try:
        return "current" if pd.to_datetime(lit).normalize() >= pd.to_datetime(target_iso).normalize() else "stale"
    except Exception:
        return "current" if lit >= target_iso else "stale"


def active_freshness_for_current_target(freshness: dict[str, Any] | None, *, book_day: Any = None) -> dict[str, Any]:
    """Return only freshness metadata that matches the current calendar target.

    Older runtime books can carry a freshness block for a date that is no longer
    the effective trading day after a calendar refresh. Do not let that stale
    block leak back into newly published replies.
    """
    raw = dict(freshness or {})
    try:
        target_info = resolve_daily_target(allow_probe=False)
    except Exception:
        return raw

    calendar_reason = target_info.get("calendar_blocking_reason")
    target_day = _date_iso(target_info.get("target_day"))
    if calendar_reason:
        return {
            "ready": False,
            "target_day": target_day,
            "target_mode": target_info.get("target_mode"),
            "blocking_reason": str(calendar_reason),
            "calendar_status": target_info.get("calendar_status"),
            "calendar_source": target_info.get("calendar_source"),
            "calendar_range": target_info.get("calendar_range"),
            "calendar_error": target_info.get("calendar_error"),
            "next_trading_day": target_info.get("next_trading_day"),
        }

    source_target = _date_iso(raw.get("target_day"))
    if not source_target or not target_day or source_target == target_day:
        return raw

    book_day_iso = _date_iso(book_day)
    if book_day_iso == target_day:
        return {}

    return {
        "ready": False,
        "target_day": target_day,
        "target_mode": target_info.get("target_mode"),
        "blocking_reason": f"当前运行时数据生效日 {book_day_iso or 'unknown'} 与目标交易日 {target_day} 不一致，请刷新运行时数据。",
        "stale_symbols": list(raw.get("stale_symbols") or []),
        "failed_symbols": list(raw.get("failed_symbols") or []),
    }


def _probe_ttl_sec() -> int:
    try:
        return max(30, int(os.getenv("GP_EOD_PROBE_TTL_SEC", "300") or "300"))
    except Exception:
        return 300


def _eod_probe_checks_ready(probe: dict[str, Any] | None) -> bool:
    if not isinstance(probe, dict) or probe.get("ready") is not True:
        return False
    expected_symbols = set(_EOD_PROBE_SYMBOLS)
    checks = probe.get("checks")
    if isinstance(checks, list) and checks:
        ready_by_symbol = {
            str(item.get("symbol")): bool(item.get("ready"))
            for item in checks
            if isinstance(item, dict) and item.get("symbol") is not None
        }
        return all(ready_by_symbol.get(symbol) is True for symbol in expected_symbols)
    try:
        return int(probe.get("ok_count") or 0) >= len(expected_symbols)
    except Exception:
        return False


def _read_eod_probe_cache(target_iso: str, ttl_sec: int) -> dict[str, Any] | None:
    path = _eod_probe_path()
    if not path.exists():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(cached, dict) or cached.get("target_day") != target_iso:
        return None
    checked_at = cached.get("checked_at")
    if not isinstance(checked_at, str) or not checked_at.strip():
        return None
    if cached.get("ready") is True:
        return cached if _eod_probe_checks_ready(cached) else None
    try:
        checked = datetime.fromisoformat(checked_at)
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - checked.astimezone(timezone.utc)).total_seconds()
        if age <= ttl_sec:
            return cached
    except Exception:
        return None
    return None


def probe_eod_daily_ready(target_day: str, *, force: bool = False) -> dict[str, Any]:
    target_ymd = _date_ymd(target_day) or str(target_day).replace("-", "")[:8]
    target_iso = _iso_from_ymd(target_ymd)
    ttl_sec = _probe_ttl_sec()
    cached = None if force else _read_eod_probe_cache(target_iso, ttl_sec)
    if cached is not None:
        return cached

    checked_at = now_iso()
    now = datetime.now(timezone.utc)
    next_retry_after = (now + timedelta(seconds=ttl_sec)).isoformat()
    hub = MarketDataHub()
    ok_count = 0
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    for symbol in _EOD_PROBE_SYMBOLS:
        try:
            df, _meta = hub.daily_ohlcv(symbol, as_of=target_iso, min_len=1, prefer_cache_only=False, force_network=True)
            last = None
            if df is not None and len(df) > 0 and "date" in df.columns:
                last = _date_iso(df.iloc[-1]["date"])
            ready = last == target_iso
            if ready:
                ok_count += 1
            checks.append({"symbol": symbol, "last": last, "ready": ready, "len": int(len(df) if df is not None else 0)})
        except Exception as ex:  # noqa: BLE001
            msg = f"{type(ex).__name__}: {ex}"
            errors.append(f"{symbol}:{msg}")
            checks.append({"symbol": symbol, "ready": False, "error": msg})
    ready = _eod_probe_checks_ready({"ready": True, "ok_count": ok_count, "checks": checks})
    probe = {
        "target_day": target_iso,
        "ready": ready,
        "checked_at": checked_at,
        "ok_count": ok_count,
        "checks": checks,
        "next_retry_after": None if ready else next_retry_after,
        "error": "; ".join(errors[:2]) if errors else None,
        "ttl_sec": ttl_sec,
    }
    try:
        _eod_probe_path().write_text(json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return probe


def resolve_daily_target(
    as_of: str | None = None,
    *,
    now=None,
    force_probe: bool = False,
    allow_probe: bool = True,
) -> MarketTimeContext:
    ms = compute_market_state(now)
    current_ymd = str(ms.target_daybook_effective_day)
    requested_raw_ymd = _date_ymd(as_of)
    requested_ymd = (
        resolve_trading_day_on_or_before(requested_raw_ymd)
        if requested_raw_ymd and hasattr(ms, "calendar_status")
        else (requested_raw_ymd or current_ymd)
    )
    calendar_status = str(getattr(ms, "calendar_status", "ok") or "ok")
    calendar_source = str(getattr(ms, "calendar_source", "") or "")
    calendar_range = {
        "start": getattr(ms, "calendar_range_start", None),
        "end": getattr(ms, "calendar_range_end", None),
    }
    calendar_reason = _calendar_blocking_reason(calendar_status, calendar_range["start"], calendar_range["end"])
    common = {
        "calendar_status": calendar_status,
        "calendar_source": calendar_source,
        "calendar_range": calendar_range,
        "next_trading_day": getattr(ms, "next_trading_day", None),
        "calendar_error": getattr(ms, "calendar_error", None),
        "calendar_blocking_reason": calendar_reason,
    }

    def context(*, effective_ymd: str, mode: str, pending: str | None = None, probe: dict[str, Any] | None = None) -> MarketTimeContext:
        return MarketTimeContext(
            decision_trade_day=_iso_from_ymd(current_ymd),
            daybook_effective_day=_iso_from_ymd(effective_ymd),
            pulse_trade_day=iso_day(getattr(ms, "target_pulse_trade_day", None)),
            pulse_slot_closed_at=getattr(ms, "target_pulse_slot_at", None),
            observed_at=now_iso(),
            market_phase=ms.market_phase,
            target_mode=mode,
            pending_eod_day=pending,
            eod_probe=probe,
            calendar_status=common["calendar_status"],
            calendar_source=common["calendar_source"],
            calendar_range=common["calendar_range"],
            calendar_error=common["calendar_error"],
            next_trading_day=iso_day(common["next_trading_day"]),
            calendar_blocking_reason=common["calendar_blocking_reason"],
        )

    if requested_ymd != current_ymd:
        return context(effective_ymd=requested_ymd, mode=TARGET_CURRENT_READY)

    if ms.market_phase == PHASE_POSTCLOSE_PENDING:
        if allow_probe:
            probe = probe_eod_daily_ready(current_ymd, force=force_probe)
        else:
            probe = _read_eod_probe_cache(_iso_from_ymd(current_ymd), _probe_ttl_sec())
        if _eod_probe_checks_ready(probe):
            target_ymd = current_ymd
            mode = TARGET_CURRENT_READY
            pending = None
        else:
            target_ymd = _previous_open_day_ymd(current_ymd)
            mode = TARGET_CURRENT_PENDING
            pending = _iso_from_ymd(current_ymd)
        return context(effective_ymd=target_ymd, mode=mode, pending=pending, probe=probe)

    if ms.market_phase in _UNFINISHED_CURRENT_DAY_PHASES:
        target_ymd = _previous_open_day_ymd(current_ymd)
        mode = TARGET_PREVIOUS_COMPLETED
    elif ms.market_phase == PHASE_NON_TRADING:
        target_ymd = current_ymd
        mode = TARGET_PREVIOUS_COMPLETED
    else:
        target_ymd = current_ymd
        mode = TARGET_CURRENT_READY
    return context(effective_ymd=target_ymd, mode=mode)


def resolve_target_trading_day(as_of: str | None = None) -> str:
    return str(resolve_daily_target(as_of).get("target_ymd") or "")


def target_day_iso(as_of: str | None = None) -> str:
    target = resolve_target_trading_day(as_of)
    return f"{target[:4]}-{target[4:6]}-{target[6:8]}"


def normalize_symbols(symbols: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for symbol in symbols:
        clean = str(symbol or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def selection_symbols(selection: dict[str, Any]) -> list[str]:
    symbols: list[str] = []
    for item in selection.get("picks") or []:
        symbol = str(item.get("symbol") or item.get("code") or "").strip()
        if symbol:
            symbols.append(symbol)
    for item in selection.get("candidate_pool") or []:
        symbol = str(item.get("symbol") or item.get("code") or "").strip()
        if symbol:
            symbols.append(symbol)
    return normalize_symbols(symbols)


def daybook_symbols(daybook: Any) -> list[str]:
    symbols = [getattr(pick, "symbol", "") for pick in getattr(daybook, "picks", [])]
    symbols.extend(getattr(pick, "symbol", "") for pick in getattr(daybook, "reserve_picks", []))
    symbols.extend(getattr(daybook, "reserve_symbols", []) or [])
    return normalize_symbols(symbols)


def book_symbols(book: Any) -> list[str]:
    symbols: list[str] = []
    for entry in getattr(book, "board", []) or []:
        symbol = getattr(entry, "symbol", None)
        if symbol:
            symbols.append(symbol)
    daybook = getattr(book, "daybook", None)
    if daybook is not None:
        symbols.extend(daybook_symbols(daybook))
    tracked = getattr(book, "tracked_universe", None)
    if tracked is not None:
        symbols.extend(getattr(tracked, "total", []) or [])
    return normalize_symbols(symbols)


def inspect_symbol_freshness(symbol: str, *, as_of: str | None = None, provider_name: str = "akshare") -> dict[str, Any]:
    qparams = {"kind": "daily", "symbol": str(symbol), "provider": provider_name}
    qid = canonical_query_id(qparams)
    ensure_query(qid, qparams)
    meta = query_meta(qid)
    target_iso = target_day_iso(as_of)
    last_item_time = str(meta.get("last_item_time") or "").strip() or None
    freshness_state = _freshness_state(last_item_time, target_iso)
    return {
        "symbol": symbol,
        "query_id": qid,
        "target_trading_day": target_iso,
        "last_fetch_at": meta.get("last_fetch_at"),
        "last_item_time": last_item_time,
        "freshness_state": freshness_state,
    }


def reconcile_daily_freshness(
    symbols: Iterable[str],
    *,
    as_of: str | None = None,
    min_len: int = 250,
    strict: bool = True,
) -> dict[str, Any]:
    target_info = resolve_daily_target(as_of)
    target_iso = str(target_info["target_day"])
    checked = normalize_symbols(symbols)
    calendar_reason = target_info.get("calendar_blocking_reason")
    if calendar_reason:
        report = {
            "target_day": target_iso,
            "target_mode": target_info.get("target_mode"),
            "daybook_trading_day": target_info.get("daybook_trading_day"),
            "pending_eod_day": target_info.get("pending_eod_day"),
            "eod_probe": target_info.get("eod_probe"),
            "calendar_status": target_info.get("calendar_status"),
            "calendar_source": target_info.get("calendar_source"),
            "calendar_range": target_info.get("calendar_range"),
            "calendar_error": target_info.get("calendar_error"),
            "next_trading_day": target_info.get("next_trading_day"),
            "checked_symbols": checked,
            "fresh_symbols": [],
            "stale_symbols": checked,
            "failed_symbols": [],
            "refreshed_symbols": [],
            "ready": False,
            "strict": strict,
            "checked_count": len(checked),
            "stale_count": len(checked),
            "failed_count": 0,
            "symbol_reports": [],
            "last_reconcile_at": now_iso(),
            "blocking_reason": str(calendar_reason),
        }
        save_daily_freshness_report(report)
        return report
    hub = MarketDataHub()
    symbol_reports: list[dict[str, Any]] = []
    fresh_symbols: list[str] = []
    stale_symbols: list[str] = []
    failed_symbols: list[str] = []
    refreshed_symbols: list[str] = []

    for symbol in checked:
        before = inspect_symbol_freshness(symbol, as_of=as_of)
        was_stale = before["freshness_state"] != "current"
        try:
            df, meta = hub.daily_ohlcv(
                symbol,
                as_of=target_iso,
                min_len=min_len,
                prefer_cache_only=False,
                force_network=was_stale,
            )
            last_date = None
            if df is not None and len(df) > 0 and "date" in df.columns:
                last_date = str(pd.to_datetime(df.iloc[-1]["date"]).date())
            state = "current" if last_date == target_iso else str(meta.get("freshness_state") or ("stale" if last_date else "missing"))
            report = {
                **before,
                "last_item_time": last_date or before["last_item_time"],
                "last_fetch_at": meta.get("last_fetch_at") or before["last_fetch_at"],
                "freshness_state": state,
                "source": meta.get("source"),
                "refresh_attempted": bool(meta.get("refresh_attempted") or was_stale),
                "refresh_succeeded": bool(meta.get("refresh_succeeded") or state == "current"),
                "strict_blocked": strict and state != "current",
                "len": int(meta.get("len") or len(df)),
                "insufficient_history": bool(meta.get("insufficient_history")),
                "target_mode": target_info.get("target_mode"),
            }
        except Exception as ex:  # noqa: BLE001
            report = {
                **before,
                "refresh_attempted": was_stale,
                "refresh_succeeded": False,
                "freshness_state": "failed_refresh" if was_stale else before["freshness_state"],
                "strict_blocked": strict,
                "error": f"{type(ex).__name__}: {ex}",
                "target_mode": target_info.get("target_mode"),
            }
        if report.get("freshness_state") == "current":
            fresh_symbols.append(symbol)
            if was_stale:
                refreshed_symbols.append(symbol)
        else:
            stale_symbols.append(symbol)
            if report.get("freshness_state") == "failed_refresh" or report.get("error"):
                failed_symbols.append(symbol)
        symbol_reports.append(report)

    ready = len(stale_symbols) == 0 and len(failed_symbols) == 0
    report = {
        "target_day": target_iso,
        "target_mode": target_info.get("target_mode"),
        "daybook_trading_day": target_info.get("daybook_trading_day"),
        "pending_eod_day": target_info.get("pending_eod_day"),
        "eod_probe": target_info.get("eod_probe"),
        "calendar_status": target_info.get("calendar_status"),
        "calendar_source": target_info.get("calendar_source"),
        "calendar_range": target_info.get("calendar_range"),
        "calendar_error": target_info.get("calendar_error"),
        "next_trading_day": target_info.get("next_trading_day"),
        "checked_symbols": checked,
        "fresh_symbols": fresh_symbols,
        "stale_symbols": stale_symbols,
        "failed_symbols": failed_symbols,
        "refreshed_symbols": refreshed_symbols,
        "ready": ready,
        "strict": strict,
        "checked_count": len(checked),
        "stale_count": len(stale_symbols),
        "failed_count": len(failed_symbols),
        "symbol_reports": symbol_reports,
        "last_reconcile_at": now_iso(),
        "blocking_reason": None if ready else f"日线数据未补齐到 {target_iso}，当前不发布正式推荐",
    }
    save_daily_freshness_report(report)
    return report


def audit_daily_freshness(*, symbols: Iterable[str] | None = None, as_of: str | None = None, limit: int = 20) -> dict[str, Any]:
    target_iso = target_day_iso(as_of)
    db_path = _history_db_path()
    counts: dict[str, int] = {}
    latest_fetches: list[dict[str, Any]] = []
    stale_examples: list[dict[str, Any]] = []
    total_daily_queries = 0
    if db_path.exists():
        for entry in list_queries(kind="daily"):
            params = dict(entry.get("params") or {})
            total_daily_queries += 1
            symbol = str(params.get("symbol") or "").strip()
            provider = str(params.get("provider") or "akshare")
            last_fetch_at = entry.get("last_fetch_at")
            lit = str(entry.get("last_item_time") or "").strip() or None
            counts[lit or "missing"] = counts.get(lit or "missing", 0) + 1
            row = {
                "symbol": symbol,
                "provider": provider,
                "last_fetch_at": last_fetch_at,
                "last_item_time": lit,
            }
            if last_fetch_at:
                latest_fetches.append(row)
            if lit and lit < target_iso and len(stale_examples) < max(limit, 1):
                stale_examples.append(row)
    focus_symbols = normalize_symbols(symbols or [])
    focus_reports = [inspect_symbol_freshness(symbol, as_of=as_of) for symbol in focus_symbols]
    focus_stale = [item for item in focus_reports if item["last_item_time"] != target_iso]
    latest_fetches.sort(key=lambda item: str(item.get("last_fetch_at") or ""), reverse=True)
    return {
        "target_day": target_iso,
        "total_daily_queries": total_daily_queries,
        "last_item_time_counts": counts,
        "latest_fetches": latest_fetches[:limit],
        "stale_examples": stale_examples[:limit],
        "focus_symbols": focus_symbols,
        "focus_reports": focus_reports,
        "focus_stale_symbols": [item["symbol"] for item in focus_stale],
    }
