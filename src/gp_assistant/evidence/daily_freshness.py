from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from ..core.paths import store_dir
from ..runtime.market_clock import compute_market_state
from ..runtime.utils import now_iso
from ..search.history_store import canonical_query_id, ensure_query, list_queries, query_meta
from ..selection_engine.datahub import MarketDataHub


def _history_db_path() -> Path:
    return store_dir() / "search" / "history.db"


def _report_path() -> Path:
    path = store_dir() / "cache" / "runtime" / "daily_freshness.json"
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


def resolve_target_trading_day(as_of: str | None = None) -> str:
    if as_of:
        try:
            return pd.to_datetime(as_of).strftime("%Y%m%d")
        except Exception:
            return str(as_of).replace("-", "")[:8]
    return str(compute_market_state().target_daybook_effective_day)


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
    freshness_state = "missing"
    if last_item_time == target_iso:
        freshness_state = "current"
    elif last_item_time:
        freshness_state = "stale"
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
    target_iso = target_day_iso(as_of)
    checked = normalize_symbols(symbols)
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
            report = {
                **before,
                "last_item_time": last_date or before["last_item_time"],
                "last_fetch_at": meta.get("last_fetch_at") or before["last_fetch_at"],
                "freshness_state": str(meta.get("freshness_state") or ("current" if last_date == target_iso else "stale")),
                "source": meta.get("source"),
                "refresh_attempted": bool(meta.get("refresh_attempted") or was_stale),
                "refresh_succeeded": bool(meta.get("refresh_succeeded") or last_date == target_iso),
                "strict_blocked": strict and last_date != target_iso,
                "len": int(meta.get("len") or len(df)),
                "insufficient_history": bool(meta.get("insufficient_history")),
            }
        except Exception as ex:  # noqa: BLE001
            report = {
                **before,
                "refresh_attempted": was_stale,
                "refresh_succeeded": False,
                "freshness_state": "failed_refresh" if was_stale else before["freshness_state"],
                "strict_blocked": strict,
                "error": f"{type(ex).__name__}: {ex}",
            }
        last_item_time = str(report.get("last_item_time") or "").strip()
        if last_item_time == target_iso and report.get("freshness_state") != "failed_refresh":
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
