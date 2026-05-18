from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd

from .plans import (
    clip,
    entry_zone_from_pick,
    finite_float,
    maybe_float,
    normalize_score,
    slot_key,
    stop_from_pick,
    takes_from_pick,
)


FEATURE_KEYS = [
    "open",
    "high",
    "low",
    "close",
    "prev_close",
    "day_open",
    "intraday_high",
    "intraday_low",
    "ret_from_open",
    "ret_from_prev_close",
    "drawdown_from_intraday_high",
    "distance_to_day_high",
    "distance_to_day_low",
    "vwap",
    "vwap_slope",
    "price_vs_vwap",
    "ema5",
    "ema13",
    "ema34",
    "ema5_slope",
    "ema13_slope",
    "trend_stack_score",
    "bars_above_vwap_count",
    "bars_below_vwap_count",
    "atr5m",
    "atr_percentile_20d",
    "realized_vol_5m",
    "realized_vol_recent",
    "compression_score",
    "range_width_recent",
    "range_breakout_score",
    "bar_body_ratio",
    "upper_shadow_ratio",
    "lower_shadow_ratio",
    "exhaustion_score",
    "slot_rel_vol",
    "cumulative_volume_run_rate",
    "amount_run_rate",
    "volume_zscore_by_slot",
    "volume_expansion_ratio",
    "dry_up_then_expand_score",
    "rs_index",
    "rs_industry",
    "rs_candidate_pool",
    "stock_rank_in_industry",
    "industry_strength_score",
    "peer_consensus_score",
    "entry_low",
    "entry_high",
    "entry_mid",
    "distance_to_entry",
    "distance_to_stop",
    "distance_to_take1",
    "rr_to_take1",
    "rr_to_take2",
    "support_cluster_score",
    "resistance_cluster_score",
    "max_chase_pct",
    "extended_flag",
    "invalidated_flag",
    "market_phase",
    "slot_at",
    "minutes_to_close",
    "is_first_30m",
    "is_lunch_reopen_window",
    "is_late_session",
    "no_new_entry_window",
    "benchmark_ret_open",
    "benchmark_price_vs_vwap",
    "market_breadth_score",
    "gate_score",
    "bars_complete",
    "benchmark_complete",
    "baseline_complete",
    "data_lag_sec",
    "provider",
    "slot_status",
]


def _num_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series([0.0] * len(df), index=df.index, dtype="float64")
    return pd.to_numeric(df[column], errors="coerce").replace([float("inf"), float("-inf")], pd.NA).ffill().fillna(0.0)


def _clean_bars(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "trade_time" in out.columns:
        out["trade_time"] = pd.to_datetime(out["trade_time"], errors="coerce")
        out = out.dropna(subset=["trade_time"]).sort_values("trade_time")
    return out.reset_index(drop=True)


def _safe_vwap(df: pd.DataFrame) -> Tuple[pd.Series, float, float]:
    close = _num_series(df, "close")
    volume = _num_series(df, "vol")
    amount = _num_series(df, "amount")
    amount = amount.where(amount > 0, close * volume)
    cum_volume = volume.cumsum()
    vwap = (amount.cumsum() / cum_volume.where(cum_volume > 0, 1.0)).replace([float("inf"), float("-inf")], pd.NA).ffill().fillna(close)
    current = finite_float(vwap.iloc[-1] if len(vwap) else None)
    prev = finite_float(vwap.iloc[-2] if len(vwap) >= 2 else current)
    return vwap, current, prev


def _ema(series: pd.Series, span: int) -> pd.Series:
    if series.empty:
        return series
    return series.ewm(span=span, adjust=False).mean()


def _atr(df: pd.DataFrame, window: int = 5) -> pd.Series:
    high = _num_series(df, "high")
    low = _num_series(df, "low")
    close = _num_series(df, "close")
    prev_close = close.shift(1).fillna(close)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(window, min_periods=1).mean().fillna(0.0)


def _ret_from_open(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    day_open = finite_float(_num_series(df, "open").iloc[0])
    close = finite_float(_num_series(df, "close").iloc[-1])
    return 0.0 if day_open <= 0 else close / day_open - 1.0


def _trade_time_series(df: pd.DataFrame) -> pd.Series:
    if "trade_time" not in df.columns:
        return pd.Series([], dtype="datetime64[ns]")
    return pd.to_datetime(df["trade_time"], errors="coerce")


def _slot_flags(slot_at: str | None) -> Dict[str, Any]:
    try:
        dt = pd.to_datetime(slot_at)
        hhmm = dt.strftime("%H:%M")
    except Exception:
        hhmm = ""
    minutes_to_close = 0
    if hhmm:
        close = "11:30" if hhmm <= "11:30" else "14:57"
        close_dt = pd.to_datetime(f"2000-01-01 {close}")
        cur_dt = pd.to_datetime(f"2000-01-01 {hhmm}")
        minutes_to_close = max(0, int((close_dt - cur_dt).total_seconds() // 60))
    return {
        "minutes_to_close": minutes_to_close,
        "is_first_30m": bool("09:35" <= hhmm <= "10:00"),
        "is_lunch_reopen_window": bool("13:05" <= hhmm <= "13:30"),
        "is_late_session": bool(hhmm >= "14:30"),
        "no_new_entry_window": bool(hhmm >= "14:30"),
    }


def _baseline_for_slot(slot_baselines: Dict[str, float], slot_at: str | None, fallback: float) -> Tuple[float, bool]:
    key = slot_key(slot_at)
    baseline = maybe_float(slot_baselines.get(key or ""))
    if baseline is not None and baseline > 0:
        return baseline, True
    return max(fallback, 1.0), False


def _baseline_cumulative(slot_baselines: Dict[str, float], slot_at: str | None, fallback_total: float) -> Tuple[float, bool]:
    key = slot_key(slot_at)
    if not key:
        return max(fallback_total, 1.0), False
    values = []
    for raw_key, raw_value in slot_baselines.items():
        if str(raw_key) <= key:
            parsed = maybe_float(raw_value)
            if parsed is not None and parsed > 0:
                values.append(parsed)
    if values:
        return max(sum(values), 1.0), True
    return max(fallback_total, 1.0), False


def _range_metrics(df: pd.DataFrame, close: float) -> Dict[str, float]:
    high = _num_series(df, "high")
    low = _num_series(df, "low")
    close_series = _num_series(df, "close")
    compression_window = df.tail(6)
    recent = df.iloc[:-1].tail(6)
    prev = df.iloc[:-2].tail(6)
    recent_high = finite_float(_num_series(recent, "high").max() if not recent.empty else high.max())
    recent_low = finite_float(_num_series(recent, "low").min() if not recent.empty else low.min())
    prev_high = finite_float(_num_series(prev, "high").max() if not prev.empty else recent_high)
    prev_low = finite_float(_num_series(prev, "low").min() if not prev.empty else recent_low)
    compression_high = finite_float(_num_series(compression_window, "high").max() if not compression_window.empty else recent_high)
    compression_low = finite_float(_num_series(compression_window, "low").min() if not compression_window.empty else recent_low)
    recent_width = 0.0 if close <= 0 else max(compression_high - compression_low, 0.0) / close
    prior_widths = ((high.rolling(6, min_periods=2).max() - low.rolling(6, min_periods=2).min()) / close_series.where(close_series > 0, 1.0)).dropna()
    prior_median = finite_float(prior_widths.iloc[:-1].median() if len(prior_widths) > 1 else recent_width, recent_width)
    compression = clip(1.0 - (recent_width / max(prior_median * 1.25, 1e-6)))
    breakout = clip((close - max(prev_high, 1e-6)) / max(close * 0.012, 1e-6))
    return {
        "recent_range_high": recent_high,
        "recent_range_low": recent_low,
        "previous_range_high": prev_high,
        "previous_range_low": prev_low,
        "range_width_recent": recent_width,
        "compression_score": compression,
        "range_breakout_score": breakout,
    }


def _industry_stats(
    *,
    symbol: str,
    pick_map: Dict[str, Any],
    symbol_returns: Dict[str, float],
) -> Dict[str, float]:
    pick = pick_map.get(symbol)
    industry = str(getattr(pick, "industry", "") or "").strip()
    industry_map = {
        item_symbol: str(getattr(item_pick, "industry", "") or "").strip()
        for item_symbol, item_pick in pick_map.items()
        if str(getattr(item_pick, "industry", "") or "").strip()
    }
    if not industry:
        return {
            "rs_industry": 0.0,
            "stock_rank_in_industry": 0.0,
            "industry_strength_score": 50.0,
            "peer_consensus_score": 50.0,
        }
    members = [item_symbol for item_symbol, item_industry in industry_map.items() if item_industry == industry and item_symbol in symbol_returns]
    returns = [symbol_returns[item_symbol] for item_symbol in members]
    industry_ret = sum(returns) / len(returns) if returns else 0.0
    ranked = sorted(members, key=lambda item_symbol: symbol_returns.get(item_symbol, 0.0), reverse=True)
    rank = ranked.index(symbol) + 1 if symbol in ranked else 0
    rank_score = 0.0 if not ranked else 100.0 * (1.0 - (rank - 1) / max(1, len(ranked) - 1))
    positive_ratio = sum(1 for value in returns if value > 0) / max(1, len(returns))
    return {
        "rs_industry": symbol_returns.get(symbol, 0.0) - industry_ret,
        "stock_rank_in_industry": float(rank),
        "industry_strength_score": normalize_score(0.5 + industry_ret * 20.0),
        "peer_consensus_score": 100.0 * positive_ratio if returns else 50.0,
        "stock_rank_score_in_industry": rank_score,
    }


def _bar_shape(open_px: float, high_px: float, low_px: float, close_px: float) -> Tuple[float, float, float, str]:
    full = max(high_px - low_px, 1e-6)
    body = abs(close_px - open_px) / full
    upper = max(high_px - max(open_px, close_px), 0.0) / full
    lower = max(min(open_px, close_px) - low_px, 0.0) / full
    if upper > 0.38 and upper > body:
        label = "upper_shadow"
    elif lower > 0.38 and lower > body:
        label = "lower_shadow"
    elif close_px >= open_px:
        label = "up_body"
    else:
        label = "down_body"
    return body, upper, lower, label


def _raw_bar_summary(df: pd.DataFrame, vwap: pd.Series, rs_index: float) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if df.empty:
        return rows
    recent = df.tail(8)
    for idx, row in recent.iterrows():
        open_px = finite_float(row.get("open"))
        high_px = finite_float(row.get("high"))
        low_px = finite_float(row.get("low"))
        close_px = finite_float(row.get("close"))
        _, upper, lower, label = _bar_shape(open_px, high_px, low_px, close_px)
        reason = "close_above_vwap" if close_px >= finite_float(vwap.loc[idx] if idx in vwap.index else close_px) else "close_below_vwap"
        if upper > 0.38:
            reason = f"{reason}, upper_shadow"
        elif lower > 0.38:
            reason = f"{reason}, lower_shadow"
        rows.append(
            {
                "trade_time": str(row.get("trade_time")) if row.get("trade_time") is not None else None,
                "close": round(close_px, 4),
                "vwap": round(finite_float(vwap.loc[idx] if idx in vwap.index else close_px), 4),
                "volume": round(finite_float(row.get("vol")), 4),
                "rs": round(float(rs_index), 6),
                "bar_shape": label,
                "reason_summary": reason,
            }
        )
    return rows


def build_feature_snapshot(
    *,
    symbol: str,
    df: pd.DataFrame,
    benchmark: pd.DataFrame | None,
    pick: Any,
    pick_map: Dict[str, Any],
    symbol_returns: Dict[str, float],
    slot_baselines: Dict[str, float],
    gate: Any | None,
    slot_at: str | None,
    trade_day: str,
    provider: str,
    market_phase: str | None = None,
    slot_status: str = "OK",
) -> Dict[str, Any]:
    bars = _clean_bars(df)
    if bars.empty:
        return {
            **{key: 0.0 for key in FEATURE_KEYS if key not in {"market_phase", "slot_at", "provider", "slot_status"}},
            "symbol": symbol,
            "trade_day": trade_day,
            "market_phase": market_phase or "",
            "slot_at": slot_at,
            "provider": provider,
            "slot_status": "UNAVAILABLE",
            "bars_complete": False,
            "benchmark_complete": bool(benchmark is not None and not benchmark.empty),
            "baseline_complete": False,
            "data_quality_score": 0.0,
            "data_quality_warnings": ["symbol_bars_missing"],
            "raw_bar_summary": [],
        }

    open_s = _num_series(bars, "open")
    high_s = _num_series(bars, "high")
    low_s = _num_series(bars, "low")
    close_s = _num_series(bars, "close")
    vol_s = _num_series(bars, "vol")
    amount_s = _num_series(bars, "amount").where(_num_series(bars, "amount") > 0, close_s * vol_s)

    last = bars.iloc[-1]
    prev = bars.iloc[-2] if len(bars) >= 2 else last
    open_px = finite_float(last.get("open"))
    high_px = finite_float(last.get("high"))
    low_px = finite_float(last.get("low"))
    close = finite_float(last.get("close"))
    prev_close = finite_float(getattr(pick, "meta", {}).get("prev_close") if pick is not None else None, finite_float(prev.get("close"), close))
    day_open = finite_float(open_s.iloc[0], open_px)
    intraday_high = finite_float(high_s.max(), high_px)
    intraday_low = finite_float(low_s.min(), low_px)
    vwap_s, vwap, prev_vwap = _safe_vwap(bars)
    ema5_s = _ema(close_s, 5)
    ema13_s = _ema(close_s, 13)
    ema34_s = _ema(close_s, 34)
    ema5 = finite_float(ema5_s.iloc[-1], close)
    ema13 = finite_float(ema13_s.iloc[-1], close)
    ema34 = finite_float(ema34_s.iloc[-1], close)
    ema5_prev = finite_float(ema5_s.iloc[-2] if len(ema5_s) >= 2 else ema5, ema5)
    ema13_prev = finite_float(ema13_s.iloc[-2] if len(ema13_s) >= 2 else ema13, ema13)
    atr_s = _atr(bars, 5)
    atr5m = finite_float(atr_s.iloc[-1])
    returns = close_s.pct_change().replace([float("inf"), float("-inf")], pd.NA).fillna(0.0)
    benchmark_bars = _clean_bars(benchmark) if benchmark is not None else pd.DataFrame()
    benchmark_ret = _ret_from_open(benchmark_bars) if not benchmark_bars.empty else 0.0
    benchmark_vwap = 0.0
    benchmark_price_vs_vwap = 0.0
    if not benchmark_bars.empty:
        _, benchmark_vwap, _ = _safe_vwap(benchmark_bars)
        benchmark_close = finite_float(_num_series(benchmark_bars, "close").iloc[-1])
        benchmark_price_vs_vwap = 0.0 if benchmark_vwap <= 0 else benchmark_close / benchmark_vwap - 1.0

    ret_from_open = 0.0 if day_open <= 0 else close / day_open - 1.0
    ret_from_prev = 0.0 if prev_close <= 0 else close / prev_close - 1.0
    rs_index = ret_from_open - benchmark_ret
    industry = _industry_stats(symbol=symbol, pick_map=pick_map, symbol_returns=symbol_returns)
    pool_avg = sum(symbol_returns.values()) / max(1, len(symbol_returns))
    rs_candidate_pool = symbol_returns.get(symbol, ret_from_open) - pool_avg
    baseline_fallback = finite_float(vol_s.iloc[:-1].tail(8).median() if len(vol_s) > 1 else vol_s.iloc[-1], finite_float(vol_s.iloc[-1]))
    slot_baseline, baseline_ok = _baseline_for_slot(slot_baselines, slot_at, baseline_fallback)
    cumulative_baseline, cumulative_baseline_ok = _baseline_cumulative(slot_baselines, slot_at, baseline_fallback * len(vol_s))
    slot_volume = finite_float(vol_s.iloc[-1])
    slot_rel_vol = slot_volume / max(slot_baseline, 1.0)
    cumulative_volume_run_rate = finite_float(vol_s.sum()) / max(cumulative_baseline, 1.0)
    amount_run_rate = finite_float(amount_s.sum()) / max(cumulative_baseline * max(close, 1.0), 1.0)
    volume_std = finite_float(vol_s.iloc[:-1].std() if len(vol_s) > 2 else slot_baseline * 0.25, slot_baseline * 0.25)
    volume_zscore = (slot_volume - slot_baseline) / max(volume_std, 1.0)
    prev_volume_median = finite_float(vol_s.iloc[:-1].tail(5).median() if len(vol_s) > 1 else slot_volume, slot_volume)
    volume_expansion_ratio = slot_volume / max(prev_volume_median, 1.0)
    dry_prev = finite_float(vol_s.iloc[-4:-1].mean() if len(vol_s) >= 4 else prev_volume_median, prev_volume_median)
    dry_up_then_expand_score = clip((slot_volume / max(dry_prev, 1.0) - 1.0) / 1.5)
    range_metrics = _range_metrics(bars, close)
    body_ratio, upper_shadow_ratio, lower_shadow_ratio, bar_shape = _bar_shape(open_px, high_px, low_px, close)
    exhaustion_score = clip(upper_shadow_ratio * 1.6 + clip(volume_expansion_ratio - 1.8) * 0.5)
    trend_stack = 0.0
    trend_stack += 0.34 if ema5 >= ema13 else 0.0
    trend_stack += 0.33 if ema13 >= ema34 else 0.0
    trend_stack += 0.33 if ema5 >= ema5_prev and ema13 >= ema13_prev else 0.0
    entry_zone = entry_zone_from_pick(pick)
    stop = stop_from_pick(pick)
    takes = takes_from_pick(pick)
    entry_low = entry_zone.get("low")
    entry_high = entry_zone.get("high")
    entry_mid = entry_zone.get("mid")
    take1 = takes[0] if takes else None
    take2 = takes[1] if len(takes) > 1 else None
    distance_to_entry = 0.0 if not entry_mid else close / max(entry_mid, 1e-6) - 1.0
    distance_to_stop = 0.0 if not stop else close / max(stop, 1e-6) - 1.0
    distance_to_take1 = 0.0 if not take1 else take1 / max(close, 1e-6) - 1.0
    risk = max((entry_mid or close) - (stop if stop is not None else close - atr5m), 1e-6)
    rr1 = 0.0 if take1 is None else max(0.0, (take1 - (entry_mid or close)) / risk)
    rr2 = 0.0 if take2 is None else max(0.0, (take2 - (entry_mid or close)) / risk)
    support_refs = [value for value in (stop, vwap, ema13, range_metrics["recent_range_low"]) if value is not None and finite_float(value) > 0]
    support_dist = min((abs(close - finite_float(value)) / max(close, 1e-6) for value in support_refs), default=1.0)
    support_cluster_score = 100.0 * clip(1.0 - support_dist / 0.025)
    resistance_refs = [value for value in (take1, range_metrics["recent_range_high"]) if value is not None and finite_float(value) > 0]
    resistance_dist = min((abs(finite_float(value) - close) / max(close, 1e-6) for value in resistance_refs), default=1.0)
    resistance_cluster_score = 100.0 * clip(1.0 - resistance_dist / 0.035)
    max_chase_pct = finite_float(getattr(pick, "meta", {}).get("max_chase_pct") if pick is not None else None, 0.025)
    extended_flag = False
    if entry_high is not None and entry_high > 0:
        extended_flag = close > entry_high * (1.0 + max_chase_pct)
    if vwap > 0:
        extended_flag = extended_flag or close > vwap * 1.035
    invalidated_flag = bool(stop is not None and close < stop)
    flags = _slot_flags(slot_at)
    gate_score = finite_float(getattr(gate, "score", 0.0) if gate is not None else 0.0, 0.0)
    breadth_score = finite_float(getattr(gate, "breadth_score", 0.0) if gate is not None else 0.0, 0.0)
    data_quality_warnings: List[str] = []
    if len(bars) < 3:
        data_quality_warnings.append("bars_too_short")
    if benchmark_bars.empty:
        data_quality_warnings.append("benchmark_missing")
    if not baseline_ok:
        data_quality_warnings.append("slot_baseline_missing")
    data_quality_score = 100.0
    data_quality_score -= 45.0 if len(bars) < 3 else 0.0
    data_quality_score -= 25.0 if benchmark_bars.empty else 0.0
    data_quality_score -= 15.0 if not baseline_ok else 0.0
    data_quality_score = max(0.0, min(100.0, data_quality_score))
    gap_pct = 0.0 if prev_close <= 0 else day_open / prev_close - 1.0
    morning_bars = bars[_trade_time_series(bars).dt.strftime("%H:%M") <= "11:30"] if "trade_time" in bars.columns else bars
    morning_return = _ret_from_open(morning_bars) if not morning_bars.empty else ret_from_open
    morning_rs_index = morning_return - benchmark_ret
    morning_pivot = finite_float(_num_series(morning_bars, "high").max() if not morning_bars.empty else high_px, high_px)
    afternoon_bars = bars[_trade_time_series(bars).dt.strftime("%H:%M") >= "13:05"] if "trade_time" in bars.columns else pd.DataFrame()
    afternoon_open_range_high = finite_float(_num_series(afternoon_bars.head(3), "high").max() if not afternoon_bars.empty else morning_pivot, morning_pivot)
    amount_median = finite_float(amount_s.iloc[:-1].tail(5).median() if len(amount_s) > 1 else amount_s.iloc[-1], amount_s.iloc[-1])
    money_flow_proxy = 1.0 if (close >= open_px and finite_float(amount_s.iloc[-1]) >= amount_median) else -1.0
    sell_climax_proxy = clip((lower_shadow_ratio * 1.4) + clip(volume_expansion_ratio - 1.5) * (1.0 if close > low_px else 0.4))

    snapshot: Dict[str, Any] = {
        "symbol": symbol,
        "trade_day": trade_day,
        "open": open_px,
        "high": high_px,
        "low": low_px,
        "close": close,
        "last_price": close,
        "prev_close": prev_close,
        "day_open": day_open,
        "intraday_high": intraday_high,
        "intraday_low": intraday_low,
        "ret_from_open": ret_from_open,
        "ret_from_prev_close": ret_from_prev,
        "drawdown_from_intraday_high": 0.0 if intraday_high <= 0 else close / intraday_high - 1.0,
        "distance_to_day_high": 0.0 if intraday_high <= 0 else close / intraday_high - 1.0,
        "distance_to_day_low": 0.0 if intraday_low <= 0 else close / intraday_low - 1.0,
        "vwap": vwap,
        "vwap_slope": 0.0 if prev_vwap <= 0 else vwap / prev_vwap - 1.0,
        "price_vs_vwap": 0.0 if vwap <= 0 else close / vwap - 1.0,
        "ema5": ema5,
        "ema13": ema13,
        "ema34": ema34,
        "ema5_slope": 0.0 if ema5_prev <= 0 else ema5 / ema5_prev - 1.0,
        "ema13_slope": 0.0 if ema13_prev <= 0 else ema13 / ema13_prev - 1.0,
        "trend_stack_score": 100.0 * trend_stack,
        "bars_above_vwap_count": int((close_s > vwap_s).sum()),
        "bars_below_vwap_count": int((close_s < vwap_s).sum()),
        "atr5m": atr5m,
        "atr_percentile_20d": finite_float(getattr(pick, "meta", {}).get("atr_percentile_20d") if pick is not None else None, 0.5),
        "realized_vol_5m": abs(finite_float(returns.iloc[-1])),
        "realized_vol_recent": finite_float(returns.tail(8).std()),
        "compression_score": 100.0 * range_metrics["compression_score"],
        "range_width_recent": range_metrics["range_width_recent"],
        "range_breakout_score": 100.0 * range_metrics["range_breakout_score"],
        "recent_range_high": range_metrics["recent_range_high"],
        "recent_range_low": range_metrics["recent_range_low"],
        "bar_body_ratio": body_ratio,
        "upper_shadow_ratio": upper_shadow_ratio,
        "lower_shadow_ratio": lower_shadow_ratio,
        "bar_shape": bar_shape,
        "exhaustion_score": 100.0 * exhaustion_score,
        "slot_rel_vol": slot_rel_vol,
        "cumulative_volume_run_rate": cumulative_volume_run_rate,
        "amount_run_rate": amount_run_rate,
        "volume_zscore_by_slot": volume_zscore,
        "volume_expansion_ratio": volume_expansion_ratio,
        "dry_up_then_expand_score": 100.0 * dry_up_then_expand_score,
        "rs_index": rs_index,
        "rs_industry": industry["rs_industry"],
        "rs_candidate_pool": rs_candidate_pool,
        "stock_rank_in_industry": industry["stock_rank_in_industry"],
        "industry_strength_score": industry["industry_strength_score"],
        "peer_consensus_score": industry["peer_consensus_score"],
        "entry_low": entry_low or 0.0,
        "entry_high": entry_high or 0.0,
        "entry_mid": entry_mid or 0.0,
        "distance_to_entry": distance_to_entry,
        "distance_to_stop": distance_to_stop,
        "distance_to_take1": distance_to_take1,
        "rr_to_take1": rr1,
        "rr_to_take2": rr2,
        "support_cluster_score": support_cluster_score,
        "resistance_cluster_score": resistance_cluster_score,
        "max_chase_pct": max_chase_pct,
        "extended_flag": bool(extended_flag),
        "invalidated_flag": bool(invalidated_flag),
        "market_phase": market_phase or "",
        "slot_at": slot_at,
        **flags,
        "benchmark_ret_open": benchmark_ret,
        "benchmark_price_vs_vwap": benchmark_price_vs_vwap,
        "market_breadth_score": breadth_score,
        "gate_score": gate_score,
        "bars_complete": bool(len(bars) >= 3),
        "benchmark_complete": bool(not benchmark_bars.empty),
        "baseline_complete": bool(baseline_ok and cumulative_baseline_ok),
        "data_lag_sec": 0.0,
        "provider": provider,
        "slot_status": slot_status,
        "day_level_alpha_score": normalize_score(getattr(pick, "scores", {}).get("final") if pick is not None else 0.0, 60.0),
        "money_flow_proxy": money_flow_proxy,
        "sell_climax_proxy": 100.0 * sell_climax_proxy,
        "gap_pct": gap_pct,
        "morning_return": morning_return,
        "morning_rs_index": morning_rs_index,
        "morning_pivot": morning_pivot,
        "afternoon_open_range_high": afternoon_open_range_high,
        "data_quality_score": data_quality_score,
        "data_quality_warnings": data_quality_warnings,
    }
    raw_summary = _raw_bar_summary(bars, vwap_s, rs_index)
    snapshot["raw_bar_summary"] = raw_summary
    for key, value in list(snapshot.items()):
        if isinstance(value, float):
            snapshot[key] = finite_float(value)
    return snapshot
