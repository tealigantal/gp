from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd


TRADING_SIGNAL = "TRADING_SIGNAL"
TRIGGER_PLAN = "TRIGGER_PLAN"
NEXT_SESSION_PLAN = "NEXT_SESSION_PLAN"
NO_TRADE = "NO_TRADE"
UNAVAILABLE = "UNAVAILABLE"

RECOMMENDATION_STATES = {
    TRADING_SIGNAL,
    TRIGGER_PLAN,
    NEXT_SESSION_PLAN,
    NO_TRADE,
    UNAVAILABLE,
}

CONTINUOUS_INTRADAY_PHASES = {"INTRADAY_AM", "INTRADAY_PM"}
NON_EXECUTION_PHASES = {
    "PREOPEN",
    "OPEN_NO_FIRST_BAR",
    "LUNCH_BREAK",
    "CLOSING_AUCTION",
    "POSTCLOSE_PENDING",
    "POSTCLOSE_READY",
    "NON_TRADING",
}


def finite_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        parsed = float(value)
        if math.isnan(parsed) or math.isinf(parsed):
            return default
        return parsed
    except Exception:
        return default


def maybe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        parsed = float(value)
        if math.isnan(parsed) or math.isinf(parsed):
            return None
        return parsed
    except Exception:
        return None


def clip(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    parsed = finite_float(value, lo)
    return max(lo, min(hi, parsed))


def score_0_100(value: Any) -> float:
    return round(100.0 * clip(value), 4)


def normalize_score(value: Any, default: float = 0.0) -> float:
    parsed = finite_float(value, default)
    if parsed <= 1.0:
        parsed *= 100.0
    return max(0.0, min(100.0, parsed))


def extract_price(levels: Dict[str, Any] | None, keys: Iterable[str]) -> Optional[float]:
    data = levels or {}
    for key in keys:
        parsed = maybe_float(data.get(key))
        if parsed is not None:
            return parsed
    return None


def extract_take(levels: Dict[str, Any] | None) -> List[float]:
    data = levels or {}
    values: List[float] = []
    for key in ("targets", "levels", "take", "prices"):
        raw = data.get(key)
        if isinstance(raw, list):
            for item in raw:
                parsed = maybe_float(item)
                if parsed is not None:
                    values.append(parsed)
    if not values:
        for key in ("price", "target", "t1", "t2"):
            parsed = extract_price(data, [key])
            if parsed is not None:
                values.append(parsed)
    return values


def entry_zone_from_pick(pick: Any) -> Dict[str, Optional[float]]:
    plan = getattr(pick, "entry_plan", {}) if pick is not None else {}
    low = extract_price(plan, ("low", "min", "start"))
    high = extract_price(plan, ("high", "max", "end"))
    mid = extract_price(plan, ("mid", "price", "entry", "anchor", "buy"))
    if low is None and mid is not None:
        low = mid
    if high is None and mid is not None:
        high = mid
    if mid is None and low is not None and high is not None:
        mid = (low + high) / 2.0
    if low is None and high is not None:
        low = high
    if high is None and low is not None:
        high = low
    return {"low": low, "high": high, "mid": mid}


def stop_from_pick(pick: Any) -> Optional[float]:
    return extract_price(
        getattr(pick, "stop_plan", {}) if pick is not None else {},
        ("price", "stop", "invalid", "invalidation", "level"),
    )


def takes_from_pick(pick: Any) -> List[float]:
    return extract_take(getattr(pick, "take_profit_plan", {}) if pick is not None else {})


def slot_key(slot_at: str | None) -> Optional[str]:
    if not slot_at:
        return None
    try:
        return pd.to_datetime(slot_at).strftime("%H:%M")
    except Exception:
        return None


def signal_valid_until_slot(slot_at: str | None, *, minutes: int = 10) -> Optional[str]:
    if not slot_at:
        return None
    try:
        return (pd.to_datetime(slot_at) + pd.Timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def is_continuous_intraday(market_phase: str | None) -> bool:
    return str(market_phase or "").upper() in CONTINUOUS_INTRADAY_PHASES


def is_non_execution_phase(market_phase: str | None) -> bool:
    return str(market_phase or "").upper() in NON_EXECUTION_PHASES


def plan_has_prices(plan: Dict[str, Any] | None) -> bool:
    if not isinstance(plan, dict):
        return False
    return any(plan.get(key) is not None for key in ("entry_low", "entry_high", "trigger_price")) and plan.get("stop_price") is not None


def derive_plan(
    *,
    features: Dict[str, Any],
    entry_type: str,
    trigger_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    take: Optional[List[float]] = None,
    invalidation_reason: str,
    invalidation_rules: List[str],
    trigger_conditions: List[str],
    confirmation_conditions: List[str],
) -> Dict[str, Any]:
    close = finite_float(features.get("close"))
    atr = max(finite_float(features.get("atr5m")), close * 0.003 if close > 0 else 0.01)
    entry_low = maybe_float(features.get("entry_low"))
    entry_high = maybe_float(features.get("entry_high"))
    entry_mid = maybe_float(features.get("entry_mid"))
    trigger = trigger_price if trigger_price is not None else maybe_float(features.get("recent_range_high"))
    if trigger is None:
        trigger = entry_high or entry_mid or close
    if entry_low is None or entry_high is None:
        band = max(trigger * 0.003, atr * 0.35)
        entry_low = trigger
        entry_high = trigger + band
    if entry_mid is None:
        entry_mid = (entry_low + entry_high) / 2.0
    stop = stop_price if stop_price is not None else maybe_float(features.get("distance_stop_price"))
    if stop is None:
        day_low = maybe_float(features.get("intraday_low"))
        stop = min(entry_low - atr, day_low if day_low is not None else entry_low - atr)
    targets = list(take or [])
    if not targets:
        risk = max(entry_mid - stop, atr, entry_mid * 0.004 if entry_mid > 0 else 0.01)
        targets = [entry_mid + 1.5 * risk, entry_mid + 2.4 * risk]
    if len(targets) == 1:
        risk = max(entry_mid - stop, atr, entry_mid * 0.004 if entry_mid > 0 else 0.01)
        targets.append(entry_mid + 2.4 * risk)
    risk = max(entry_mid - stop, 1e-6)
    rr1 = max(0.0, (targets[0] - entry_mid) / risk)
    rr2 = max(0.0, (targets[1] - entry_mid) / risk)
    triggered = close >= trigger and entry_low <= close <= max(entry_high, trigger * 1.012)
    return {
        "trigger_price": round(float(trigger), 4),
        "entry_low": round(float(entry_low), 4),
        "entry_high": round(float(entry_high), 4),
        "entry_mid": round(float(entry_mid), 4),
        "entry_type": entry_type,
        "stop_price": round(float(stop), 4),
        "invalidation_reason": invalidation_reason,
        "take1": round(float(targets[0]), 4),
        "take2": round(float(targets[1]), 4),
        "rr_to_take1": round(float(rr1), 4),
        "rr_to_take2": round(float(rr2), 4),
        "signal_valid_until_slot": signal_valid_until_slot(str(features.get("slot_at") or "")),
        "triggered": bool(triggered),
        "invalidation_rules": list(invalidation_rules),
        "trigger_conditions": list(trigger_conditions),
        "confirmation_conditions": list(confirmation_conditions),
    }


def compact_strategy(candidate: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "strategy_name": candidate.get("strategy_name"),
        "eligible": bool(candidate.get("eligible")),
        "score": finite_float(candidate.get("raw_score")),
        "reason_codes": list(candidate.get("reason_codes") or [])[:8],
        "reject_reasons": list(candidate.get("reject_reasons") or [])[:8],
    }


def compact_context(context: Dict[str, Any]) -> Dict[str, Any]:
    score = dict(context.get("score_breakdown") or {})
    return {
        "symbol": context.get("symbol"),
        "name": context.get("name"),
        "rank": context.get("rank"),
        "recommendation_state": context.get("recommendation_state"),
        "champion_strategy": context.get("champion_strategy"),
        "live_score": score.get("live_score"),
        "champion_strategy_score": context.get("champion_strategy_score"),
        "execution_quality_score": score.get("execution_quality_score"),
        "rr_score": score.get("rr_score"),
        "relative_strength_score": score.get("relative_strength_score"),
        "risk_penalty": score.get("risk_penalty"),
        "data_quality_score": score.get("data_quality_score"),
    }
