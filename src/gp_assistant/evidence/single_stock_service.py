from __future__ import annotations

import re
from typing import Any, Dict, Optional

import pandas as pd

from ..contracts.objects import MarketBook, SingleStockAnalysisArtifact
from ..evidence.daily_freshness import target_day_iso
from ..selection_engine.datahub import MarketDataHub
from ..strategy.single_stock import build_single_stock_strategy_view


SYMBOL_RE = re.compile(r"^(?:60|68|00|30)\d{4}$")
MIN_HISTORY_BARS = 120


def normalize_single_stock_symbol(value: Any) -> str | None:
    text = str(value or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 6:
        digits = digits[:6]
    return digits if SYMBOL_RE.match(digits) else None


def _name_from_book(symbol: str, book: MarketBook | None) -> str | None:
    if book is None:
        return None
    for entry in list(getattr(book, "board", []) or []):
        if getattr(entry, "symbol", None) == symbol and getattr(entry, "name", None):
            return str(entry.name)
    for pick in list(getattr(getattr(book, "daybook", None), "picks", []) or []):
        if getattr(pick, "symbol", None) == symbol and getattr(pick, "name", None):
            return str(pick.name)
    return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _round_float(value: Any, ndigits: int = 4) -> float | None:
    try:
        parsed = float(value)
        if pd.isna(parsed):
            return None
        return round(parsed, ndigits)
    except Exception:
        return None


def _pct_change(df: pd.DataFrame, bars: int) -> float | None:
    if len(df) <= bars or "close" not in df.columns:
        return None
    start = _round_float(df["close"].iloc[-(bars + 1)], 8)
    end = _round_float(df["close"].iloc[-1], 8)
    if start is None or end is None or start <= 0:
        return None
    return round((end / start - 1.0) * 100.0, 2)


def _kline_summary(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        return {}
    tail20 = df.tail(20)
    last = df.iloc[-1]
    volume_ratio_5d = None
    if len(df) >= 6 and "volume" in df.columns:
        recent_avg = pd.to_numeric(df["volume"].iloc[-6:-1], errors="coerce").mean()
        last_volume = _round_float(last.get("volume"), 8)
        if recent_avg and last_volume is not None:
            volume_ratio_5d = round(last_volume / float(recent_avg), 2)
    return {
        "last_close": _round_float(last.get("close"), 2),
        "last_open": _round_float(last.get("open"), 2),
        "last_high": _round_float(last.get("high"), 2),
        "last_low": _round_float(last.get("low"), 2),
        "return_1d_pct": _pct_change(df, 1),
        "return_5d_pct": _pct_change(df, 5),
        "return_20d_pct": _pct_change(df, 20),
        "high_20d": _round_float(tail20["high"].max() if "high" in tail20.columns else None, 2),
        "low_20d": _round_float(tail20["low"].min() if "low" in tail20.columns else None, 2),
        "volume_ratio_5d": volume_ratio_5d,
        "bars": int(len(df)),
    }


def _last_date(df: pd.DataFrame) -> str | None:
    if df.empty or "date" not in df.columns:
        return None
    try:
        return str(pd.to_datetime(df["date"].iloc[-1]).date())
    except Exception:
        return str(df["date"].iloc[-1])


def _overall_state(trade_plan: Dict[str, Any], *, stale: bool, insufficient: bool) -> str:
    if insufficient:
        return "UNAVAILABLE"
    state = str(((trade_plan.get("diagnostics") or {}).get("execution_state") or "")).lower()
    if stale:
        return "STALE_OBSERVE"
    if state == "actionable":
        return "PLAN_READY"
    if state == "waiting_pullback":
        return "WAIT_PULLBACK"
    if state in {"below_support", "breakdown_risk"}:
        return "RISK_HIGH"
    return "WATCH_ONLY"


def analyze_single_stock(symbol: str, *, book: MarketBook | None = None, as_of: str | None = None) -> SingleStockAnalysisArtifact:
    normalized = normalize_single_stock_symbol(symbol)
    if normalized is None:
        raw = str(symbol or "").strip()
        return SingleStockAnalysisArtifact(
            symbol=raw,
            name=None,
            as_of=as_of,
            data_status={"ok": False, "error": "invalid_symbol", "required": "6-digit A-share code"},
            overall_state="UNAVAILABLE",
            reason_codes=["invalid_symbol"],
        )

    try:
        query_as_of = as_of or target_day_iso()
    except Exception:
        query_as_of = as_of
    hub = MarketDataHub()
    try:
        df, meta = hub.daily_ohlcv(normalized, as_of=query_as_of, min_len=MIN_HISTORY_BARS, prefer_cache_only=False)
    except Exception as ex:  # noqa: BLE001
        return SingleStockAnalysisArtifact(
            symbol=normalized,
            name=_name_from_book(normalized, book),
            as_of=query_as_of,
            data_status={"ok": False, "error": f"{type(ex).__name__}: {ex}"},
            overall_state="UNAVAILABLE",
            reason_codes=["daily_fetch_failed"],
            data_provenance={"provider": "MarketDataHub"},
        )

    df = df.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df[df["date"].notna()].sort_values("date").reset_index(drop=True)
    last_date = _last_date(df)
    freshness_state = str((meta or {}).get("freshness_state") or "").strip().lower()
    stale = bool(freshness_state and freshness_state != "current")
    insufficient = bool((meta or {}).get("insufficient_history")) or len(df) < MIN_HISTORY_BARS
    reason_codes: list[str] = []
    if df.empty:
        reason_codes.append("daily_empty")
    if stale:
        reason_codes.append("daily_stale")
    if insufficient:
        reason_codes.append("insufficient_history")

    champion: Dict[str, Any] = {}
    trade_plan: Dict[str, Any] = {}
    strategy_error = None
    if not df.empty and not insufficient and not stale:
        try:
            env_grade = str((getattr(book, "regime", {}) or {}).get("grade") or "C") if book is not None else "C"
            strategy_view = build_single_stock_strategy_view(normalized, df, env_grade=env_grade)
            champion = _jsonable(strategy_view.get("champion") or {})
            trade_plan = _jsonable(strategy_view.get("trade_plan") or {})
        except Exception as ex:  # noqa: BLE001
            strategy_error = f"{type(ex).__name__}: {ex}"
            reason_codes.append("strategy_eval_failed")

    data_status = {
        "ok": bool(not df.empty and strategy_error is None),
        "target_day": query_as_of,
        "last_date": last_date,
        "freshness_state": freshness_state or None,
        "insufficient_history": insufficient,
        "analysis_ready": bool(not df.empty and not insufficient and not stale and strategy_error is None),
        "bars": int(len(df)),
        "strategy_error": strategy_error,
    }
    return SingleStockAnalysisArtifact(
        symbol=normalized,
        name=_name_from_book(normalized, book),
        as_of=query_as_of,
        last_date=last_date,
        data_status=_jsonable(data_status),
        kline_summary=_jsonable(_kline_summary(df)),
        champion=champion,
        trade_plan=trade_plan,
        overall_state=_overall_state(trade_plan, stale=stale, insufficient=insufficient),
        reason_codes=reason_codes,
        data_provenance=_jsonable({"daily_meta": meta, "provider": "MarketDataHub"}),
    )
