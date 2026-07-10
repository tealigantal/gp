from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List

import pandas as pd

from ..market_memory.feature_vector import build_feature_vector
from ..market_memory.store import MarketMemoryEvent, make_market_event
from ..strategy.indicators import compute_indicators


@dataclass
class SignalBuildResult:
    current_event: MarketMemoryEvent | None
    historical_events: List[MarketMemoryEvent]
    last_close: float | None
    last_date: str | None
    data_status: Dict[str, Any]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if value < lo else hi if value > hi else value


def _date_at(df: pd.DataFrame, idx: int) -> str:
    if "date" in df.columns:
        return pd.to_datetime(df["date"].iloc[idx]).date().isoformat()
    return str(idx)


def _market_regime_score(market_context: Dict[str, Any]) -> float:
    grade = str(market_context.get("market_regime") or market_context.get("grade") or "C").upper()
    return {"A": 0.82, "B": 0.66, "C": 0.48, "D": 0.28}.get(grade, 0.5)


def _liquidity_score(amount_5d_avg: float) -> float:
    return _clamp((amount_5d_avg - 3e8) / 2.2e9)


def _row_features(df: pd.DataFrame, idx: int, market_context: Dict[str, Any]) -> Dict[str, Any]:
    row = df.iloc[idx]
    close = _safe_float(row.get("close"))
    ma10 = _safe_float(row.get("ma10"))
    ma20 = _safe_float(row.get("ma20"))
    ma60 = _safe_float(row.get("ma60"))
    slope20 = _safe_float(row.get("slope20"))
    atr_pct = abs(_safe_float(row.get("atr_pct")))
    volume_ratio = _safe_float(row.get("volratio10"), 1.0)
    amount_5d_avg = _safe_float(row.get("amount_5d_avg"))
    recent = df.iloc[max(0, idx - 59) : idx + 1]
    support = _safe_float(recent["close"].quantile(0.30) if "close" in recent.columns and len(recent) else close)
    high20_prev = _safe_float(df["high"].iloc[max(0, idx - 20) : idx].max() if idx > 0 and "high" in df.columns else close)
    extension_ma20 = (close / ma20 - 1.0) if close and ma20 else 0.0
    support_distance = (close - support) / close if close and support else 0.0
    trend_raw = 0.5 + 3.5 * slope20
    if close and ma20 and close > ma20:
        trend_raw += 0.15
    if ma20 and ma60 and ma20 > ma60:
        trend_raw += 0.12
    trend_strength = _clamp(trend_raw)
    pullback_quality = _clamp(1.0 - abs(extension_ma20) / 0.12)
    if close and high20_prev and close >= high20_prev * 0.985:
        pullback_quality = max(0.35, pullback_quality - 0.12)
    price_position = _clamp(1.0 - max(0.0, support_distance) / 0.12)
    return {
        "close": close,
        "ma10": ma10,
        "ma20": ma20,
        "ma60": ma60,
        "support": support,
        "high20_prev": high20_prev,
        "trend_strength": trend_strength,
        "pullback_quality": pullback_quality,
        "volume_ratio": max(0.0, volume_ratio),
        "atr_pct": atr_pct,
        "extension_pct": extension_ma20,
        "support_distance_pct": support_distance,
        "liquidity_score": _liquidity_score(amount_5d_avg),
        "market_regime_score": _market_regime_score(market_context),
        "industry_strength_score": _safe_float(market_context.get("industry_strength_score"), 0.5),
        "price_position_score": price_position,
        "amount_5d_avg": amount_5d_avg,
    }


def _signal_type(features: Dict[str, Any]) -> str:
    close = _safe_float(features.get("close"))
    high20 = _safe_float(features.get("high20_prev"))
    ma20 = _safe_float(features.get("ma20"))
    support_distance = _safe_float(features.get("support_distance_pct"))
    trend = _safe_float(features.get("trend_strength"))
    pullback = _safe_float(features.get("pullback_quality"))
    volume = _safe_float(features.get("volume_ratio"), 1.0)
    if close and high20 and close >= high20 * 0.99 and volume >= 1.15:
        return "breakout_pressure"
    if trend >= 0.58 and pullback >= 0.55 and support_distance <= 0.10:
        return "breakout_pullback" if close and ma20 and close >= ma20 else "trend_pullback"
    if trend >= 0.55:
        return "trend_continuation"
    return "structure_watch"


def _outcome(df: pd.DataFrame, idx: int, features: Dict[str, Any]) -> Dict[str, Any]:
    entry = _safe_float(df["close"].iloc[idx])
    if entry <= 0 or idx + 5 >= len(df):
        return {"complete": False}
    fwd = df.iloc[idx + 1 : idx + 6]
    closes = pd.to_numeric(fwd["close"], errors="coerce")
    highs = pd.to_numeric(fwd["high"], errors="coerce") if "high" in fwd.columns else closes
    lows = pd.to_numeric(fwd["low"], errors="coerce") if "low" in fwd.columns else closes
    ret1 = _safe_float(closes.iloc[0] / entry - 1.0)
    ret3 = _safe_float(closes.iloc[2] / entry - 1.0)
    ret5 = _safe_float(closes.iloc[4] / entry - 1.0)
    max_profit = _safe_float(highs.max() / entry - 1.0)
    max_drawdown = _safe_float(lows.min() / entry - 1.0)
    atr_pct = max(0.015, _safe_float(features.get("atr_pct"), 0.03))
    stop_level = -max(0.03, atr_pct * 1.3)
    target_level = max(0.03, atr_pct * 1.5)
    failure_modes: list[str] = []
    if ret3 < 0:
        failure_modes.append("negative_3d_return")
    if max_drawdown <= stop_level:
        failure_modes.append("drawdown_stop_like")
    if max_profit < target_level and ret3 <= 0:
        failure_modes.append("no_follow_through")
    return {
        "complete": True,
        "return_1d": ret1,
        "return_3d": ret3,
        "return_5d": ret5,
        "max_profit": max_profit,
        "max_drawdown": max_drawdown,
        "stop_hit": bool(max_drawdown <= stop_level),
        "target_hit": bool(max_profit >= target_level),
        "success": bool(ret3 > 0),
        "failure_modes": failure_modes,
    }


def _make_event(
    *,
    df: pd.DataFrame,
    idx: int,
    symbol: str,
    name: str | None,
    industry: str | None,
    market_context: Dict[str, Any],
    with_outcome: bool,
) -> MarketMemoryEvent:
    features = _row_features(df, idx, market_context)
    signal_type = _signal_type(features)
    vector = build_feature_vector(features)
    as_of = _date_at(df, idx)
    event_context = {
        "market_regime": market_context.get("market_regime") or market_context.get("grade") or "C",
        "industry": industry,
        "name": name,
        "as_of": as_of,
    }
    return make_market_event(
        as_of=as_of,
        symbol=symbol,
        signal_type=signal_type,
        feature_vector=vector,
        features={**features, "signal_type": signal_type, "name": name, "industry": industry},
        market_context=event_context,
        outcome=_outcome(df, idx, features) if with_outcome else {"complete": False},
        data_provenance={"source": "daily_ohlcv", "feature_engine": "signal_engine.daily"},
    )


def build_signal_events_for_symbol(
    *,
    symbol: str,
    df: pd.DataFrame,
    as_of: str,
    name: str | None = None,
    industry: str | None = None,
    market_context: Dict[str, Any] | None = None,
    max_history: int = 60,
    historical_market_context_resolver: Callable[[str], Dict[str, Any]] | None = None,
    historical_event_mode: str = "window",
) -> SignalBuildResult:
    market_context = dict(market_context or {})
    if df is None or len(df) < 80:
        return SignalBuildResult(None, [], None, None, {"ok": False, "reason": "insufficient_history"})
    indicator_columns = {"ma10", "ma20", "ma60", "slope20", "atr_pct", "volratio10", "amount_5d_avg"}
    feat = df.copy() if indicator_columns.issubset(df.columns) else compute_indicators(df)
    feat = feat.dropna(subset=["close"]).reset_index(drop=True)
    if len(feat) < 80:
        return SignalBuildResult(None, [], None, None, {"ok": False, "reason": "insufficient_feature_history"})
    try:
        cutoff = pd.to_datetime(as_of).normalize()
        if "date" in feat.columns:
            feat = feat[pd.to_datetime(feat["date"], errors="coerce") <= cutoff].reset_index(drop=True)
    except Exception:
        pass
    if len(feat) < 80:
        return SignalBuildResult(None, [], None, None, {"ok": False, "reason": "no_rows_as_of"})
    last_idx = len(feat) - 1
    current = _make_event(
        df=feat,
        idx=last_idx,
        symbol=symbol,
        name=name,
        industry=industry,
        market_context=market_context,
        with_outcome=False,
    )
    end = max(60, last_idx - 5)
    start = max(60, end - max(1, int(max_history)))
    if historical_event_mode not in {"window", "newly_matured"}:
        raise ValueError("historical_event_mode must be window or newly_matured")
    historical_indices = range(start, end) if historical_event_mode == "window" else range(max(start, end - 1), end)
    historical: List[MarketMemoryEvent] = []
    for idx in historical_indices:
        historical_date = _date_at(feat, idx)
        historical_context = (
            dict(historical_market_context_resolver(historical_date) or {})
            if historical_market_context_resolver is not None
            else market_context
        )
        historical.append(
            _make_event(
                df=feat,
                idx=idx,
                symbol=symbol,
                name=name,
                industry=industry,
                market_context=historical_context,
                with_outcome=True,
            )
        )
    return SignalBuildResult(
        current_event=current,
        historical_events=[event for event in historical if bool((event.outcome or {}).get("complete") is True)],
        last_close=_safe_float(feat["close"].iloc[last_idx]),
        last_date=_date_at(feat, last_idx),
        data_status={"ok": True, "rows": len(feat), "as_of": _date_at(feat, last_idx)},
    )
