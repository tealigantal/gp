from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Optional

import pandas as pd

from ..risk.noise_q import grade_noise
from . import library as strat_lib
from .champion import choose_champion
from .chip_model import compute_chip
from .indicators import compute_indicators
from .ts_cv import purged_walk_forward


EXEC_ACTIONABLE_MAX_GAP_PCT = 0.03
EXEC_WAITING_MAX_GAP_PCT = 0.08
EXEC_BELOW_SUPPORT_TOL_PCT = -0.005
MIN_RR_FOR_ACTIONABLE = 0.3


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        parsed = float(value)
        if pd.isna(parsed):
            return None
        return parsed
    except Exception:
        return None


def _latest_setup(mod: Any, df_feat: pd.DataFrame) -> Any:
    try:
        detect = getattr(mod, "detect_setups", None)
        setups = detect(df_feat) if callable(detect) else []
        return setups[-1] if setups else None
    except Exception:
        return None


def evaluate_symbol_strategies(symbol: str, df_feat: pd.DataFrame, q_grade: Optional[str] = None) -> Dict[str, Any]:
    """Return per-strategy evaluation inputs consumed by champion selection."""
    out: Dict[str, Any] = {}
    try:
        cv = purged_walk_forward(df_feat)
        cv_dict = getattr(cv, "__dict__", {})
    except Exception:
        cv_dict = {
            "k": 0,
            "win_rate_5d_mean": 0.0,
            "win_rate_5d_std": 0.0,
            "mean_return_5d_mean": 0.0,
            "mean_return_5d_std": 0.0,
            "drawdown_proxy_mean": 0.0,
        }

    last_idx = max(0, len(df_feat) - 1)
    for sid, mod in (strat_lib.REGISTRY or {}).items():
        try:
            detect = getattr(mod, "detect_setups", None)
            setups = detect(df_feat) if callable(detect) else []
        except Exception:
            setups = []

        ev_dict: Dict[str, Any] = {}
        try:
            ev = getattr(mod, "event_study", None)
            st_meta = (getattr(strat_lib, "METADATA", {}) or {}).get(str(sid), {})
            prefer_obs = bool(st_meta.get("prefer_observation_only", False))
            setup_idx = int(getattr(setups[-1], "idx", last_idx)) if setups else last_idx
            setup_age = max(0, last_idx - setup_idx)
            if callable(ev) and setups and setup_age <= 15 and not prefer_obs:
                ev_stats = ev(df_feat, setups)
                ev_dict = getattr(ev_stats, "__dict__", {})
        except Exception:
            ev_dict = {}

        try:
            setup_idx = int(getattr(setups[-1], "idx", last_idx)) if setups else last_idx
        except Exception:
            setup_idx = last_idx
        setup_age = max(0, last_idx - setup_idx)
        out[str(sid)] = {
            "cv": cv_dict,
            "event": ev_dict,
            "setup": {"last_idx": setup_idx, "age": setup_age, "count": len(setups)},
        }
    return out


def _recent_bands(df_feat: pd.DataFrame) -> Dict[str, float]:
    recent = df_feat.tail(max(30, min(60, len(df_feat))))
    if recent.empty or "close" not in recent.columns:
        return {}
    s1 = _safe_float(recent["close"].quantile(0.30))
    s2 = _safe_float(recent["close"].quantile(0.50))
    r1 = _safe_float(recent["close"].quantile(0.80))
    if s1 is None or s2 is None or r1 is None:
        return {}
    return {"S1": s1, "S2": s2, "R1": r1, "R2": r1 * 1.02}


def _chip_bands(chip: Dict[str, Any] | None) -> Dict[str, float]:
    if not isinstance(chip, dict):
        return {}
    low = _safe_float(chip.get("band_90_low"))
    mid = _safe_float(chip.get("avg_cost"))
    high = _safe_float(chip.get("band_90_high"))
    if low is None or high is None:
        return {}
    if mid is None:
        mid = (low + high) / 2.0
    return {"S1": low, "S2": mid, "R1": high, "R2": high * 1.02}


def _execution_diagnostics(df_feat: pd.DataFrame, bands: Dict[str, Any], setup_idx: int) -> Dict[str, Any]:
    diag: Dict[str, Any] = {
        "setup_idx": setup_idx,
        "setup_age": max(0, len(df_feat) - 1 - setup_idx),
        "stale": False,
    }
    last_close = _safe_float(df_feat["close"].iloc[-1] if "close" in df_feat.columns and len(df_feat) else None)
    s1 = _safe_float(bands.get("S1"))
    r1 = _safe_float(bands.get("R1"))
    if last_close is None or s1 is None:
        diag.update({"execution_state": "observe_only", "actionable": False})
        return diag

    signed_entry_gap = (last_close - s1) / last_close if last_close else None
    entry_gap_abs = abs(signed_entry_gap) if signed_entry_gap is not None else None
    reward_risk = None
    if r1 is not None and last_close > s1:
        reward_risk = (r1 - last_close) / max(1e-6, last_close - s1)

    if signed_entry_gap is None:
        state = "observe_only"
        actionable = False
    elif signed_entry_gap <= EXEC_BELOW_SUPPORT_TOL_PCT:
        state = "below_support"
        actionable = False
    elif signed_entry_gap <= 0.0:
        state = "breakdown_risk"
        actionable = False
    elif entry_gap_abs is not None and entry_gap_abs <= EXEC_ACTIONABLE_MAX_GAP_PCT:
        actionable = bool(reward_risk is not None and reward_risk >= MIN_RR_FOR_ACTIONABLE)
        state = "actionable" if actionable else "observe_only"
    elif entry_gap_abs is not None and entry_gap_abs <= EXEC_WAITING_MAX_GAP_PCT:
        state = "waiting_pullback"
        actionable = False
    else:
        state = "observe_only"
        actionable = False

    diag.update(
        {
            "execution_state": state,
            "entry_gap_pct": entry_gap_abs,
            "signed_entry_gap_pct": signed_entry_gap,
            "reward_risk": reward_risk,
            "actionable": actionable,
        }
    )
    return diag


def build_trade_plan_from_champion(
    symbol: str,
    df_feat: pd.DataFrame,
    champion: Dict[str, Any] | None,
    *,
    chip: Dict[str, Any] | None = None,
    q_grade: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a daily trade-plan summary for a champion strategy."""
    champ = dict(champion or {})
    strategy_id = str(champ.get("strategy") or "").strip()
    mod = (strat_lib.REGISTRY or {}).get(strategy_id)
    if mod is None or df_feat.empty:
        return {
            "diagnostics": {"execution_state": "observe_only", "actionable": False},
            "invalidation": [],
            "risk": {"no_averaging_down": True},
        }

    setup = _latest_setup(mod, df_feat)
    setup_idx = len(df_feat) - 1
    if setup is not None:
        try:
            setup_idx = int(getattr(setup, "idx", setup_idx))
        except Exception:
            setup_idx = len(df_feat) - 1

    bands: Dict[str, Any] = {}
    band_source = "unknown"
    try:
        key_bands = getattr(mod, "key_bands", None)
        if callable(key_bands) and setup is not None:
            bands = dict(key_bands(df_feat, setup) or {})
            if bands:
                band_source = "strategy_key_bands"
    except Exception:
        bands = {}
    if not bands:
        bands = _chip_bands(chip)
        band_source = "chip_fallback" if bands else band_source
    if not bands:
        bands = _recent_bands(df_feat)
        band_source = "recent_window_fallback" if bands else band_source

    diag = _execution_diagnostics(df_feat, bands, setup_idx)
    if band_source:
        diag["band_source"] = band_source
    if q_grade:
        diag["q_grade"] = q_grade

    invalidation: list[str] = []
    try:
        invalid = getattr(mod, "invalidation", None)
        if callable(invalid) and setup is not None:
            invalidation = [str(item) for item in (invalid(setup) or []) if str(item).strip()]
    except Exception:
        invalidation = []

    s1 = _safe_float(bands.get("S1"))
    s2 = _safe_float(bands.get("S2"))
    r1 = _safe_float(bands.get("R1"))
    r2 = _safe_float(bands.get("R2"))
    return {
        "bands": bands,
        "execution_bands": bands,
        "structural_bands": bands,
        "structural_band_source": band_source,
        "execution_band_source": band_source,
        "diagnostics": diag,
        "entry": {"kind": "zone", "low": s1, "high": s2, "price": s1},
        "stop": {"kind": "close_below_support", "price": s1, "text": "收盘有效跌破支撑带"},
        "take_profit": {"kind": "targets", "price": r1, "targets": [value for value in (r1, r2) if value is not None]},
        "invalidation": invalidation,
        "risk": {"stop_loss": "收盘有效跌破支撑带", "time_stop": "2-3日不强则走", "no_averaging_down": True},
        "symbol": symbol,
        "strategy": strategy_id,
    }


def build_single_stock_strategy_view(symbol: str, daily: pd.DataFrame, *, env_grade: str = "C") -> Dict[str, Any]:
    """Compute indicator, champion, and trade-plan facts for one symbol."""
    feat = compute_indicators(daily)
    chip_res, chip_meta = compute_chip(feat)
    chip_dict = asdict(chip_res)
    q_grade = grade_noise(feat, env_grade if env_grade in {"A", "B", "C", "D"} else "C")
    strategies = evaluate_symbol_strategies(symbol, feat, q_grade)
    champion = choose_champion([{"symbol": symbol, "strategies": strategies}]).get(symbol, {})
    trade_plan = build_trade_plan_from_champion(symbol, feat, champion, chip=chip_dict, q_grade=q_grade)
    last = feat.iloc[-1] if len(feat) else {}
    return {
        "features": feat,
        "q_grade": q_grade,
        "chip": chip_dict,
        "chip_meta": chip_meta,
        "strategies": strategies,
        "champion": champion,
        "trade_plan": trade_plan,
        "last_close": _safe_float(last.get("close") if hasattr(last, "get") else None),
    }
