from __future__ import annotations

from typing import Dict, Iterable, Optional

import pandas as pd

from ..contracts.objects import DayBook, SlotGate, SymbolPulse, TrackedUniverse
from ..core.logging import logger
from ..evidence.market_service import fetch_intraday_bundle, load_slot_volume_baselines
from ..intraday.features import build_feature_snapshot
from ..intraday.plans import (
    NEXT_SESSION_PLAN,
    NO_TRADE,
    TRADING_SIGNAL,
    TRIGGER_PLAN,
    UNAVAILABLE,
    entry_zone_from_pick,
    finite_float,
    slot_key,
    stop_from_pick,
    takes_from_pick,
)
from ..intraday.scoring import (
    action_for_state,
    build_entry_readiness,
    build_risk_pack,
    build_score_breakdown,
    can_open_for_state,
    determine_recommendation_state,
    execution_state_for_recommendation,
    signal_type_for_strategy,
)
from ..intraday.strategies import StrategyRegistry, select_champion
from ..runtime.market_clock import PHASE_INTRADAY_AM, PHASE_INTRADAY_PM, PHASE_LUNCH_BREAK, PHASE_NON_TRADING


BUY_STATES = {"breakout_buy", "reclaim_buy", "afternoon_relaunch_buy", "trend_continuation_buy"}


def _market_phase_from_slot(slot_at: str | None) -> str:
    if not slot_at:
        return PHASE_NON_TRADING
    try:
        hhmm = pd.to_datetime(slot_at).strftime("%H:%M")
    except Exception:
        return PHASE_NON_TRADING
    if "09:35" <= hhmm <= "11:30":
        return PHASE_INTRADAY_AM
    if "11:30" < hhmm < "13:05":
        return PHASE_LUNCH_BREAK
    if "13:05" <= hhmm <= "14:55":
        return PHASE_INTRADAY_PM
    return PHASE_NON_TRADING


def _ret_from_open(df: pd.DataFrame | None) -> float:
    if df is None or df.empty:
        return 0.0
    close = pd.to_numeric(df.get("close"), errors="coerce").ffill().fillna(0.0)
    open_ = pd.to_numeric(df.get("open"), errors="coerce").ffill().fillna(0.0)
    if close.empty or open_.empty or float(open_.iloc[0]) <= 0:
        return 0.0
    return float(close.iloc[-1]) / float(open_.iloc[0]) - 1.0


def _safe_vwap(df: pd.DataFrame | None) -> tuple[float | None, float | None]:
    if df is None or df.empty:
        return None, None
    close = pd.to_numeric(df.get("close"), errors="coerce").ffill().fillna(0.0)
    volume = pd.to_numeric(df.get("vol"), errors="coerce").fillna(0.0)
    amount = pd.to_numeric(df.get("amount"), errors="coerce").fillna(0.0)
    amount = amount.where(amount > 0, close * volume)
    cum_volume = volume.cumsum()
    valid = cum_volume > 0
    if not bool(valid.any()):
        return None, None
    vwap_series = amount.cumsum() / cum_volume.where(valid, 1.0)
    current = float(vwap_series.iloc[-1]) if len(vwap_series) else None
    prev = float(vwap_series.iloc[-2]) if len(vwap_series) >= 2 else current
    return current, prev


def _daily_rank_score(symbol: str, reco_rank: Dict[str, int], reco_size: int) -> float:
    if symbol not in reco_rank:
        return 0.0
    if reco_size <= 1:
        return 1.0
    return 1.0 - float((reco_rank[symbol] - 1) / max(1, reco_size - 1))


def _missing_data_pulse(
    *,
    symbol: str,
    pick,
    daily_rank_score: float,
    provider: str,
    trade_day: str,
    slot_at: str | None,
    reason: str,
) -> SymbolPulse:
    entry_zone = entry_zone_from_pick(pick)
    stop = stop_from_pick(pick)
    take = takes_from_pick(pick)
    risk_pack = {
        "main_risks": [reason],
        "do_not_chase_reason": "Real intraday bars are unavailable; no trade value can be inferred.",
        "what_would_improve": ["restore_symbol_bars", "restore_benchmark_and_slot_baseline"],
        "what_would_cancel": ["data_stays_unavailable"],
        "data_quality_warnings": [reason],
        "market_gate_risks": [],
        "late_session_risk": False,
        "stop_too_far_risk": False,
        "rr_not_enough_risk": False,
    }
    return SymbolPulse(
        symbol=symbol,
        execution_state="unavailable",
        action="WATCH",
        can_open=False,
        live_score=0.0,
        pulse_score=0.0,
        daily_rank_score=daily_rank_score,
        exec_score=0.0,
        signal_type="unavailable",
        entry_zone=entry_zone,
        stop=stop,
        take=take,
        invalidated=False,
        extended=False,
        reason_codes=[reason],
        provider=provider,
        trade_day=trade_day,
        slot_at=slot_at,
        recommendation_state=UNAVAILABLE,
        feature_snapshot={
            "symbol": symbol,
            "trade_day": trade_day,
            "slot_at": slot_at,
            "provider": provider,
            "slot_status": "UNAVAILABLE",
            "bars_complete": False,
            "data_quality_score": 0.0,
            "data_quality_warnings": [reason],
        },
        strategy_candidates=[],
        champion_strategy="NO_TRADE_STRATEGY",
        champion_strategy_score=0.0,
        execution_plan={},
        score_breakdown={"live_score": 0.0, "data_quality_score": 0.0},
        risk_pack=risk_pack,
    )


def evaluate_slot_pulses(
    *,
    daybook: DayBook,
    tracked_universe: TrackedUniverse,
    bars: Dict[str, pd.DataFrame],
    benchmark: pd.DataFrame | None,
    slot_baselines: Dict[str, Dict[str, float]],
    gate: SlotGate | None = None,
    slot_at: str | None,
    trade_day: str,
    provider: str,
    previous_actions: Optional[Dict[str, str]] = None,
    market_phase: str | None = None,
    slot_status: str = "OK",
) -> Dict[str, SymbolPulse]:
    previous_actions = previous_actions or {}
    pick_map = {pick.symbol: pick for pick in [*daybook.picks, *daybook.reserve_picks]}
    reco_symbols = [pick.symbol for pick in [*daybook.picks, *daybook.reserve_picks]]
    reco_rank = {symbol: idx + 1 for idx, symbol in enumerate(reco_symbols)}
    reco_size = max(1, len(reco_symbols))
    symbol_returns = {symbol: _ret_from_open(df) for symbol, df in bars.items() if df is not None and not df.empty}
    inferred_phase = market_phase or _market_phase_from_slot(slot_at)
    registry = StrategyRegistry()

    pulses: Dict[str, SymbolPulse] = {}
    for symbol in tracked_universe.total:
        pick = pick_map.get(symbol)
        rank_score = _daily_rank_score(symbol, reco_rank, reco_size)
        df = bars.get(symbol)
        if df is None or df.empty:
            pulses[symbol] = _missing_data_pulse(
                symbol=symbol,
                pick=pick,
                daily_rank_score=rank_score,
                provider=provider,
                trade_day=trade_day,
                slot_at=slot_at,
                reason="symbol_data_missing",
            )
            continue

        feature_snapshot = build_feature_snapshot(
            symbol=symbol,
            df=df,
            benchmark=benchmark,
            pick=pick,
            pick_map=pick_map,
            symbol_returns=symbol_returns,
            slot_baselines=slot_baselines.get(symbol, {}),
            gate=gate,
            slot_at=slot_at,
            trade_day=trade_day,
            provider=provider,
            market_phase=inferred_phase,
            slot_status=slot_status,
        )
        candidates = registry.run_all(feature_snapshot)
        champion = select_champion(candidates)
        recommendation_state = determine_recommendation_state(
            features=feature_snapshot,
            champion=champion,
            gate=gate,
            market_phase=inferred_phase,
            previous_action=previous_actions.get(symbol),
        )
        score_breakdown = build_score_breakdown(feature_snapshot, champion)
        risk_pack = build_risk_pack(
            features=feature_snapshot,
            champion=champion,
            gate=gate,
            recommendation_state=recommendation_state,
        )
        if recommendation_state in {UNAVAILABLE, NO_TRADE}:
            score_breakdown["live_score"] = 0.0 if recommendation_state == UNAVAILABLE else score_breakdown.get("live_score", 0.0)
        action = action_for_state(recommendation_state)
        can_open = can_open_for_state(recommendation_state)
        plan = dict(champion.plan or {})
        if plan:
            plan["entry_readiness"] = build_entry_readiness(
                features=feature_snapshot,
                plan=plan,
                gate=gate,
                market_phase=inferred_phase,
                previous_action=previous_actions.get(symbol),
            )
        execution_state = execution_state_for_recommendation(recommendation_state, champion.strategy_name)
        if recommendation_state == TRIGGER_PLAN:
            execution_state = (
                execution_state_for_recommendation(TRADING_SIGNAL, champion.strategy_name)
                if bool(plan.get("triggered"))
                else "wait_pullback"
            )
        if bool(feature_snapshot.get("extended_flag")) and recommendation_state != TRADING_SIGNAL:
            execution_state = "extended"
        if bool(feature_snapshot.get("invalidated_flag")):
            execution_state = "invalidated"
        entry_zone = {
            "low": plan.get("entry_low") or feature_snapshot.get("entry_low"),
            "high": plan.get("entry_high") or feature_snapshot.get("entry_high"),
            "mid": plan.get("entry_mid") or feature_snapshot.get("entry_mid"),
            "trigger": plan.get("trigger_price"),
            "type": plan.get("entry_type"),
        }
        take = [value for value in (plan.get("take1"), plan.get("take2")) if value is not None]
        candidate_dicts = [candidate.model_dump() for candidate in candidates]
        reason_codes = list(champion.reason_codes or [])
        if recommendation_state == TRADING_SIGNAL:
            reason_codes.append("trading_signal_ready")
        elif recommendation_state == TRIGGER_PLAN:
            reason_codes.append("waiting_for_trigger")
        elif recommendation_state == NEXT_SESSION_PLAN:
            reason_codes.append("next_session_plan")
        elif recommendation_state == UNAVAILABLE:
            reason_codes.append("data_unavailable")
        else:
            reason_codes.append("no_trade")
        entry_blockers = list((plan.get("entry_readiness") or {}).get("blockers") or [])
        if entry_blockers and recommendation_state == TRIGGER_PLAN:
            reason_codes.append("entry_conditions_pending")
            reason_codes.extend([f"entry_check_{blocker}_not_met" for blocker in entry_blockers[:6]])
        pulse = SymbolPulse(
            symbol=symbol,
            last_bar_at=str(pd.to_datetime(df["trade_time"].iloc[-1]).isoformat()) if "trade_time" in df.columns else slot_at,
            pulse_score=float(score_breakdown.get("live_score", 0.0)),
            momentum_state="up" if finite_float(feature_snapshot.get("rs_index")) > 0 else ("down" if finite_float(feature_snapshot.get("rs_index")) < 0 else "flat"),
            stretch_state="high" if bool(feature_snapshot.get("extended_flag")) else "normal",
            liquidity_state="good" if finite_float(feature_snapshot.get("slot_rel_vol")) >= 0.8 else "thin",
            execution_state=execution_state,
            invalidated=bool(feature_snapshot.get("invalidated_flag")),
            entry_distance_pct=finite_float(feature_snapshot.get("distance_to_entry")),
            flags=[f"slot_rel_vol={finite_float(feature_snapshot.get('slot_rel_vol')):.2f}"],
            evidence_refs=[symbol],
            live_score=float(score_breakdown.get("live_score", 0.0)),
            daily_rank_score=rank_score,
            exec_score=float(score_breakdown.get("execution_quality_score", 0.0)),
            action=action,
            can_open=can_open,
            signal_type=signal_type_for_strategy(champion.strategy_name),
            entry_zone=entry_zone,
            stop=plan.get("stop_price") or stop_from_pick(pick),
            take=take or takes_from_pick(pick),
            vwap=feature_snapshot.get("vwap"),
            orb30_high=feature_snapshot.get("recent_range_high"),
            orb30_low=feature_snapshot.get("recent_range_low"),
            rs_index=feature_snapshot.get("rs_index"),
            rs_industry=feature_snapshot.get("rs_industry"),
            slot_rel_vol=feature_snapshot.get("slot_rel_vol"),
            extended=bool(feature_snapshot.get("extended_flag")),
            reason_codes=reason_codes,
            provider=provider,
            volume_baseline=(slot_baselines.get(symbol, {}).get(slot_key(slot_at) or "") if slot_key(slot_at) else None),
            trade_day=trade_day,
            slot_at=slot_at,
            recommendation_state=recommendation_state,
            feature_snapshot=feature_snapshot,
            raw_bar_summary=list(feature_snapshot.get("raw_bar_summary") or []),
            strategy_candidates=candidate_dicts,
            champion_strategy=champion.strategy_name,
            champion_strategy_score=float(champion.raw_score),
            execution_plan=plan,
            score_breakdown={key: float(value) for key, value in score_breakdown.items()},
            strategy_context={
                "champion_strategy": champion.strategy_name,
                "champion_strategy_score": float(champion.raw_score),
                "strategy_reason_codes": list(champion.reason_codes or []),
                "strategy_reject_reasons": list(champion.reject_reasons or []),
                "competing_strategies": sorted(
                    [candidate.model_dump() for candidate in candidates if candidate.strategy_name != "NO_TRADE_STRATEGY"],
                    key=lambda item: float(item.get("raw_score") or 0.0),
                    reverse=True,
                )[:3],
            },
            risk_pack=risk_pack,
        )
        pulses[symbol] = pulse
    return pulses


def score_intraday_gate(
    *,
    snapshot: pd.DataFrame | None,
    benchmark: pd.DataFrame | None,
    pulses: Dict[str, SymbolPulse],
    tracked_universe: TrackedUniverse,
    data_complete: bool,
) -> SlotGate:
    if not data_complete or benchmark is None or benchmark.empty or snapshot is None or snapshot.empty:
        return SlotGate(state="UNAVAILABLE", score=0.0, reasons=["data_quality_incomplete"])

    pct_col = "pct_chg" if "pct_chg" in snapshot.columns else ("chg" if "chg" in snapshot.columns else None)
    if pct_col is None:
        return SlotGate(state="UNAVAILABLE", score=0.0, reasons=["snapshot_columns_missing"])
    pct = pd.to_numeric(snapshot[pct_col], errors="coerce").dropna()
    if pct.empty:
        return SlotGate(state="UNAVAILABLE", score=0.0, reasons=["snapshot_empty"])
    up_ratio = float((pct > 0).mean())
    mean_chg = float(pct.mean())
    if up_ratio >= 0.58 and mean_chg > 0.3:
        breadth_score = 100.0
    elif up_ratio >= 0.50 and mean_chg > 0.0:
        breadth_score = 70.0
    elif up_ratio >= 0.42:
        breadth_score = 45.0
    else:
        breadth_score = 20.0

    benchmark_ret = _ret_from_open(benchmark)
    benchmark_vwap, _ = _safe_vwap(benchmark)
    benchmark_close = float(pd.to_numeric(benchmark["close"].iloc[-1], errors="coerce") or 0.0)
    if benchmark_vwap is not None and benchmark_close > benchmark_vwap and benchmark_ret > 0:
        benchmark_score = 100.0
    elif benchmark_vwap is not None and benchmark_close > benchmark_vwap:
        benchmark_score = 70.0
    elif benchmark_ret > -0.003:
        benchmark_score = 45.0
    else:
        benchmark_score = 20.0

    reco_pulses = [pulses[symbol] for symbol in tracked_universe.reco if symbol in pulses]
    median_slot_rel_vol = (
        float(pd.Series([pulse.slot_rel_vol for pulse in reco_pulses if pulse.slot_rel_vol is not None]).median())
        if reco_pulses
        else 0.0
    )
    if median_slot_rel_vol >= 0.9:
        liquidity_score = 100.0
    elif median_slot_rel_vol >= 0.7:
        liquidity_score = 70.0
    elif median_slot_rel_vol >= 0.5:
        liquidity_score = 45.0
    else:
        liquidity_score = 20.0

    buyable_count = sum(
        1
        for pulse in reco_pulses
        if pulse.recommendation_state in {TRADING_SIGNAL, TRIGGER_PLAN} and not pulse.invalidated
    )
    gate_score = 0.45 * breadth_score + 0.35 * benchmark_score + 0.20 * liquidity_score
    if gate_score >= 60.0 and buyable_count >= 2:
        state = "ALLOW"
    elif gate_score >= 45.0 and buyable_count >= 1:
        state = "DEGRADED"
    elif buyable_count == 0 or gate_score < 45.0:
        state = "BLOCKED"
    else:
        state = "UNAVAILABLE"
    reasons = [
        f"buyable_count={buyable_count}",
        f"up_ratio={up_ratio:.3f}",
        f"mean_chg={mean_chg:.3f}",
        f"median_slot_rel_vol={median_slot_rel_vol:.3f}",
    ]
    return SlotGate(
        state=state,
        score=float(gate_score),
        reasons=reasons,
        breadth_score=float(breadth_score),
        benchmark_score=float(benchmark_score),
        liquidity_score=float(liquidity_score),
        buyable_count=int(buyable_count),
        metrics={
            "up_ratio": up_ratio,
            "mean_chg": mean_chg,
            "benchmark_ret_open": benchmark_ret,
            "benchmark_close": benchmark_close,
            "benchmark_vwap": benchmark_vwap,
            "median_slot_rel_vol": median_slot_rel_vol,
        },
    )


def compute_slot_pulse_package(
    *,
    daybook: DayBook,
    tracked_universe: TrackedUniverse,
    trade_day: str,
    slot_at: str,
    previous_actions: Optional[Dict[str, str]] = None,
    benchmark_symbol: Optional[str] = None,
) -> Dict[str, object]:
    bundle = fetch_intraday_bundle(
        trading_day=trade_day,
        slot_at=slot_at,
        symbols=tracked_universe.total,
        benchmark_symbol=benchmark_symbol,
    )
    data_complete = (
        bundle["symbols_received"] == bundle["symbols_expected"]
        and bool(bundle["benchmark_received"])
        and bundle.get("snapshot") is not None
        and not bundle["snapshot"].empty
    )
    baselines = load_slot_volume_baselines(trade_day, tracked_universe.total)
    inferred_phase = _market_phase_from_slot(slot_at)
    provisional_gate = SlotGate(state="ALLOW", score=100.0, reasons=["pre_gate"])
    provisional_pulses = evaluate_slot_pulses(
        daybook=daybook,
        tracked_universe=tracked_universe,
        bars=bundle["bars"],
        benchmark=bundle["benchmark"],
        slot_baselines=baselines,
        gate=provisional_gate,
        slot_at=slot_at,
        trade_day=trade_day,
        provider=str(bundle["provider"]),
        previous_actions=previous_actions,
        market_phase=inferred_phase,
        slot_status=("OK" if data_complete else "DEGRADED"),
    )
    gate = score_intraday_gate(
        snapshot=bundle["snapshot"],
        benchmark=bundle["benchmark"],
        pulses=provisional_pulses,
        tracked_universe=tracked_universe,
        data_complete=bool(data_complete),
    )
    pulses = evaluate_slot_pulses(
        daybook=daybook,
        tracked_universe=tracked_universe,
        bars=bundle["bars"],
        benchmark=bundle["benchmark"],
        slot_baselines=baselines,
        gate=gate,
        slot_at=slot_at,
        trade_day=trade_day,
        provider=str(bundle["provider"]),
        previous_actions=previous_actions,
        market_phase=inferred_phase,
        slot_status=("OK" if data_complete else "DEGRADED"),
    )
    return {
        "pulses": pulses,
        "gate": gate,
        "bundle": bundle,
    }


def apply_pulse(book, symbols: Iterable[str], *, target_trade_day: str | None, target_slot_at: str | None):
    if not target_trade_day or not target_slot_at:
        for symbol in symbols:
            state = book.symbol_states.get(symbol)
            if state is not None:
                state.is_stale = True
                state.stale_reason = "no_closed_bar_yet"
                state.execution_state = "unavailable"
                state.recommendation_state = UNAVAILABLE
                state.action = "WATCH"
                state.can_open = False
        book.last_closed_5m = None
        return book
    tracked = TrackedUniverse(
        reco=[pick.symbol for pick in book.daybook.picks],
        reserve=[pick.symbol for pick in book.daybook.reserve_picks],
        portfolio=[],
        total=[str(symbol).strip() for symbol in symbols if str(symbol).strip()],
    )
    try:
        pkg = compute_slot_pulse_package(
            daybook=book.daybook,
            tracked_universe=tracked,
            trade_day=target_trade_day,
            slot_at=target_slot_at,
        )
        pulses = pkg["pulses"]
        for symbol, pulse in pulses.items():
            book.symbol_states[symbol] = pulse
        book.last_closed_5m = target_slot_at
    except Exception as ex:  # noqa: BLE001
        logger.warning("[pulse5m] apply_pulse failed trade_day=%s slot=%s error=%s", target_trade_day, target_slot_at, ex)
        raise
    return book


# Disabled module archived: production path removed; original code is retained as comments.
# from __future__ import annotations
#
# from typing import Dict, Iterable, Optional
#
# import pandas as pd
#
# from ..contracts.objects import DayBook, SlotGate, SymbolPulse, TrackedUniverse
# from ..core.logging import logger
# from ..evidence.market_service import fetch_intraday_bundle, load_slot_volume_baselines
#
#
# BUY_STATES = {"breakout_buy", "reclaim_buy", "afternoon_relaunch_buy"}
#
#
# def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
#     return max(lo, min(hi, float(value)))
#
#
# def _extract_price(levels: dict, keys: list[str]) -> float | None:
#     for key in keys:
#         value = levels.get(key)
#         if value is None:
#             continue
#         try:
#             return float(value)
#         except Exception:
#             continue
#     return None
#
#
# def _extract_take(levels: dict) -> list[float]:
#     values: list[float] = []
#     for key in ["targets", "levels", "take", "prices"]:
#         raw = levels.get(key)
#         if isinstance(raw, list):
#             for item in raw:
#                 try:
#                     values.append(float(item))
#                 except Exception:
#                     continue
#     if not values:
#         for key in ["price", "target", "t1", "t2"]:
#             value = _extract_price(levels, [key])
#             if value is not None:
#                 values.append(value)
#     return values
#
#
# def _entry_zone_from_pick(pick) -> dict:
#     plan = pick.entry_plan if pick is not None else {}
#     low = _extract_price(plan, ["low", "min", "start"])
#     high = _extract_price(plan, ["high", "max", "end"])
#     price = _extract_price(plan, ["mid", "price", "entry", "anchor", "buy"])
#     if low is None and price is not None:
#         low = price
#     if high is None and price is not None:
#         high = price
#     if low is None and high is None:
#         mid = price
#     else:
#         if low is None:
#             low = high
#         if high is None:
#             high = low
#         mid = price if price is not None else ((float(low) + float(high)) / 2.0 if low is not None and high is not None else None)
#     return {"low": low, "high": high, "mid": mid}
#
#
# def _trade_time(df: pd.DataFrame) -> pd.Series:
#     return pd.to_datetime(df["trade_time"], errors="coerce")
#
#
# def _safe_vwap(df: pd.DataFrame) -> tuple[float | None, float | None]:
#     amount = pd.to_numeric(df.get("amount"), errors="coerce").fillna(0.0)
#     volume = pd.to_numeric(df.get("vol"), errors="coerce").fillna(0.0)
#     cum_amount = amount.cumsum()
#     cum_volume = volume.cumsum()
#     valid = cum_volume > 0
#     if not valid.any():
#         return None, None
#     vwap_series = cum_amount.where(valid, 0.0) / cum_volume.where(valid, 1.0)
#     current = float(vwap_series.iloc[-1]) if len(vwap_series) else None
#     prev = float(vwap_series.iloc[-2]) if len(vwap_series) >= 2 else current
#     return current, prev
#
#
# def _ret_from_open(df: pd.DataFrame) -> float:
#     if df.empty:
#         return 0.0
#     open_px = float(pd.to_numeric(df["open"].iloc[0], errors="coerce") or 0.0)
#     close_px = float(pd.to_numeric(df["close"].iloc[-1], errors="coerce") or 0.0)
#     if open_px <= 0:
#         return 0.0
#     return close_px / open_px - 1.0
#
#
# def _orb30(df: pd.DataFrame) -> tuple[float | None, float | None]:
#     times = _trade_time(df)
#     orb = df[times.dt.strftime("%H:%M") <= "10:00"]
#     if orb.empty:
#         return None, None
#     high = pd.to_numeric(orb["high"], errors="coerce").dropna()
#     low = pd.to_numeric(orb["low"], errors="coerce").dropna()
#     return (float(high.max()) if not high.empty else None, float(low.min()) if not low.empty else None)
#
#
# def _upper_wick_exhausted(bar: pd.Series) -> bool:
#     open_px = float(pd.to_numeric(bar.get("open"), errors="coerce") or 0.0)
#     close_px = float(pd.to_numeric(bar.get("close"), errors="coerce") or 0.0)
#     high_px = float(pd.to_numeric(bar.get("high"), errors="coerce") or 0.0)
#     low_px = float(pd.to_numeric(bar.get("low"), errors="coerce") or 0.0)
#     body = abs(close_px - open_px)
#     upper = high_px - max(open_px, close_px)
#     full = max(high_px - low_px, 1e-6)
#     return upper > max(body * 1.2, full * 0.35)
#
#
# def _slot_key(slot_at: str | None) -> Optional[str]:
#     if not slot_at:
#         return None
#     return pd.to_datetime(slot_at).strftime("%H:%M")
#
#
# def _state_signal_quality(state: str) -> float:
#     mapping = {
#         "breakout_buy": 1.00,
#         "reclaim_buy": 0.90,
#         "afternoon_relaunch_buy": 0.85,
#         "wait_pullback": 0.55,
#         "observe": 0.30,
#         "extended": 0.10,
#         "invalidated": 0.00,
#         "unavailable": 0.00,
#     }
#     return mapping.get(state, 0.0)
#
#
# def _late_session_watch(slot_at: str | None, previous_action: str | None) -> bool:
#     if not slot_at:
#         return False
#     slot_dt = pd.to_datetime(slot_at)
#     return slot_dt.strftime("%H:%M") >= "14:30" and previous_action != "BUY"
#
#
# def evaluate_slot_pulses(
#     *,
#     daybook: DayBook,
#     tracked_universe: TrackedUniverse,
#     bars: Dict[str, pd.DataFrame],
#     benchmark: pd.DataFrame | None,
#     slot_baselines: Dict[str, Dict[str, float]],
#     gate: SlotGate | None = None,
#     slot_at: str | None,
#     trade_day: str,
#     provider: str,
#     previous_actions: Optional[Dict[str, str]] = None,
# ) -> Dict[str, SymbolPulse]:
#     previous_actions = previous_actions or {}
#     pick_map = {pick.symbol: pick for pick in [*daybook.picks, *daybook.reserve_picks]}
#     reco_symbols = [pick.symbol for pick in [*daybook.picks, *daybook.reserve_picks]]
#     reco_rank = {symbol: idx + 1 for idx, symbol in enumerate(reco_symbols)}
#     reco_size = max(1, len(reco_symbols))
#     benchmark_ret = _ret_from_open(benchmark) if benchmark is not None and not benchmark.empty else 0.0
#     benchmark_vwap, _ = _safe_vwap(benchmark) if benchmark is not None and not benchmark.empty else (None, None)
#
#     symbol_returns = {symbol: _ret_from_open(df) for symbol, df in bars.items() if df is not None and not df.empty}
#     industry_map = {
#         symbol: (pick.industry or "").strip()
#         for symbol, pick in pick_map.items()
#         if isinstance(pick.industry, str) and pick.industry.strip()
#     }
#     industry_returns: Dict[str, float] = {}
#     for industry in sorted(set(industry_map.values())):
#         members = [symbol for symbol, mapped in industry_map.items() if mapped == industry and symbol in symbol_returns]
#         if len(members) >= 2:
#             industry_returns[industry] = float(sum(symbol_returns[symbol] for symbol in members) / len(members))
#
#     pulses: Dict[str, SymbolPulse] = {}
#     for symbol in tracked_universe.total:
#         pick = pick_map.get(symbol)
#         entry_zone = _entry_zone_from_pick(pick) if pick is not None else {"low": None, "high": None, "mid": None}
#         stop = _extract_price(pick.stop_plan if pick is not None else {}, ["price", "stop", "invalid", "invalidation", "level"])
#         take = _extract_take(pick.take_profit_plan if pick is not None else {})
#         daily_rank_score = 0.0
#         if symbol in reco_rank:
#             if reco_size == 1:
#                 daily_rank_score = 1.0
#             else:
#                 daily_rank_score = 1.0 - float((reco_rank[symbol] - 1) / max(1, reco_size - 1))
#         reason_codes: list[str] = []
#         df = bars.get(symbol)
#         if df is None or df.empty:
#             pulses[symbol] = SymbolPulse(
#                 symbol=symbol,
#                 execution_state="unavailable",
#                 action="WATCH",
#                 invalidated=False,
#                 live_score=100 * 0.62 * daily_rank_score,
#                 daily_rank_score=daily_rank_score,
#                 exec_score=0.0,
#                 signal_type="unavailable",
#                 can_open=False,
#                 entry_zone=entry_zone,
#                 stop=stop,
#                 take=take,
#                 extended=False,
#                 reason_codes=["symbol_data_missing"],
#                 provider=provider,
#                 trade_day=trade_day,
#                 slot_at=slot_at,
#             )
#             continue
#
#         df = df.copy()
#         df["trade_time"] = pd.to_datetime(df["trade_time"], errors="coerce")
#         df = df.dropna(subset=["trade_time"]).sort_values("trade_time").reset_index(drop=True)
#         last = df.iloc[-1]
#         prev = df.iloc[-2] if len(df) >= 2 else last
#         slot_dt = pd.to_datetime(slot_at) if slot_at else pd.to_datetime(last["trade_time"])
#         last_close = float(pd.to_numeric(last["close"], errors="coerce") or 0.0)
#         prev_close = float(pd.to_numeric(prev["close"], errors="coerce") or 0.0)
#         low_px = float(pd.to_numeric(last["low"], errors="coerce") or 0.0)
#         close_above_vwap = False
#         vwap, prev_vwap = _safe_vwap(df)
#         if vwap is not None:
#             close_above_vwap = last_close > vwap
#         rs_index = symbol_returns.get(symbol, 0.0) - benchmark_ret
#         industry = industry_map.get(symbol)
#         rs_industry = None
#         if industry and industry in industry_returns:
#             rs_industry = symbol_returns.get(symbol, 0.0) - industry_returns[industry]
#         else:
#             reason_codes.append("industry_rs_unavailable")
#         slot_key = _slot_key(slot_at)
#         baseline = slot_baselines.get(symbol, {}).get(slot_key or "") if slot_key else None
#         slot_volume = float(pd.to_numeric(last.get("vol"), errors="coerce") or 0.0)
#         slot_rel_vol = None
#         if baseline and baseline > 0:
#             slot_rel_vol = slot_volume / baseline
#         else:
#             reason_codes.append("slot_baseline_missing")
#         orb30_high, orb30_low = _orb30(df)
#         if orb30_high is None or orb30_low is None:
#             reason_codes.append("orb30_unavailable")
#
#         prev_bar_high = float(pd.to_numeric(prev.get("high"), errors="coerce") or 0.0)
#         entry_high = entry_zone.get("high")
#         entry_mid = entry_zone.get("mid")
#         above_stop = True if stop is None else last_close >= float(stop)
#         invalidated = False if stop is None else last_close < float(stop)
#         extended = False
#         if entry_high is not None and vwap is not None:
#             extended = last_close > max(float(entry_high) * 1.025, float(vwap) * 1.015)
#         elif entry_high is not None:
#             extended = last_close > float(entry_high) * 1.025
#
#         slot_time = slot_dt.strftime("%H:%M")
#         recent_exhausted = len(df) >= 2 and _upper_wick_exhausted(df.iloc[-1]) and _upper_wick_exhausted(df.iloc[-2])
#         rs_industry_ok = True if rs_industry is None else rs_industry > 0
#         breakout_window = ("10:00" <= slot_time <= "11:20") or ("13:05" <= slot_time <= "14:30")
#         reclaim_window = slot_time >= "10:00"
#         afternoon_window = "13:05" <= slot_time <= "14:00"
#         morning_local_high = None
#         morning_bars = df[_trade_time(df).dt.strftime("%H:%M") <= "11:30"]
#         if not morning_bars.empty:
#             morning_local_high = float(pd.to_numeric(morning_bars["high"], errors="coerce").max())
#
#         if invalidated:
#             execution_state = "invalidated"
#             signal_type = "invalidated"
#         elif (
#             breakout_window
#             and orb30_high is not None
#             and vwap is not None
#             and last_close > orb30_high
#             and last_close > vwap
#             and rs_index > 0
#             and rs_industry_ok
#             and (slot_rel_vol is not None and slot_rel_vol >= 1.30)
#             and (entry_high is None or last_close <= float(entry_high) * 1.025)
#             and above_stop
#             and not recent_exhausted
#         ):
#             execution_state = "breakout_buy"
#             signal_type = "breakout"
#         elif (
#             reclaim_window
#             and vwap is not None
#             and entry_high is not None
#             and entry_mid is not None
#             and low_px <= max(vwap, float(entry_mid))
#             and last_close > max(vwap, float(entry_mid))
#             and last_close > prev_bar_high
#             and rs_index > 0
#             and (slot_rel_vol is not None and slot_rel_vol >= 0.80)
#             and last_close <= min(float(entry_high) * 1.005, float(entry_mid) * 1.01)
#             and above_stop
#             and not recent_exhausted
#         ):
#             execution_state = "reclaim_buy"
#             signal_type = "reclaim"
#         elif (
#             afternoon_window
#             and vwap is not None
#             and last_close > vwap
#             and morning_local_high is not None
#             and last_close > morning_local_high
#             and rs_index > 0
#             and (slot_rel_vol is not None and slot_rel_vol >= 1.0)
#             and not extended
#         ):
#             execution_state = "afternoon_relaunch_buy"
#             signal_type = "afternoon_relaunch"
#         elif extended:
#             execution_state = "extended"
#             signal_type = "extended"
#         else:
#             near_entry = False
#             if entry_mid is not None and entry_mid > 0:
#                 near_entry = abs(last_close - float(entry_mid)) / float(entry_mid) <= 0.015
#             if not invalidated and near_entry:
#                 execution_state = "wait_pullback"
#                 signal_type = "wait_pullback"
#             else:
#                 execution_state = "observe"
#                 signal_type = "observe"
#
#         vwap_alignment = 0.0
#         if vwap is not None and close_above_vwap:
#             if prev_vwap is not None and prev_close > prev_vwap:
#                 vwap_alignment = 1.0
#             else:
#                 vwap_alignment = 0.60
#         rs_index_score = _clip(rs_index / 0.02)
#         rs_industry_score = _clip((rs_industry or 0.0) / 0.02) if rs_industry is not None else 0.0
#         volume_score = _clip((slot_rel_vol or 0.0) / 1.8) if slot_rel_vol is not None else 0.0
#         if entry_mid is not None and float(entry_mid) > 0:
#             location_score = 1.0 - min(abs(last_close - float(entry_mid)) / float(entry_mid), 0.03) / 0.03
#         else:
#             location_score = 0.0
#             reason_codes.append("entry_zone_missing")
#         exec_score = (
#             28.0 * _state_signal_quality(execution_state)
#             + 18.0 * vwap_alignment
#             + 16.0 * rs_index_score
#             + 12.0 * rs_industry_score
#             + 14.0 * volume_score
#             + 12.0 * location_score
#             - 25.0 * (1.0 if extended else 0.0)
#             - 60.0 * (1.0 if invalidated else 0.0)
#         )
#         live_score = 100.0 * (0.62 * daily_rank_score + 0.38 * (exec_score / 100.0))
#         action = "INVALID" if invalidated else "WATCH"
#         can_open = False
#         if execution_state in BUY_STATES:
#             if gate is not None and gate.state == "ALLOW":
#                 action = "BUY"
#                 can_open = True
#                 if _late_session_watch(slot_at, previous_actions.get(symbol)):
#                     action = "WATCH"
#                     can_open = False
#                     reason_codes.append("late_session_new_signal")
#             elif gate is not None and gate.state == "UNAVAILABLE":
#                 action = "WATCH"
#                 reason_codes.append("gate_unavailable")
#             else:
#                 action = "WATCH"
#                 if gate is not None:
#                     reason_codes.append(f"gate_{gate.state.lower()}")
#         elif execution_state == "extended":
#             action = "WATCH"
#
#         pulses[symbol] = SymbolPulse(
#             symbol=symbol,
#             last_bar_at=pd.to_datetime(last["trade_time"]).isoformat(),
#             momentum_state="up" if rs_index > 0 else ("down" if rs_index < 0 else "flat"),
#             stretch_state="high" if extended else "normal",
#             liquidity_state="good" if (slot_rel_vol or 0.0) >= 0.8 else "thin",
#             execution_state=execution_state,
#             invalidated=invalidated,
#             entry_distance_pct=(None if entry_mid in (None, 0) else float(last_close / float(entry_mid) - 1.0)),
#             flags=[f"slot_rel_vol={slot_rel_vol:.2f}" for _ in [0] if slot_rel_vol is not None],
#             evidence_refs=[symbol],
#             live_score=live_score,
#             daily_rank_score=daily_rank_score,
#             exec_score=exec_score,
#             action=action,
#             can_open=can_open,
#             signal_type=signal_type,
#             entry_zone=entry_zone,
#             stop=stop,
#             take=take,
#             vwap=vwap,
#             orb30_high=orb30_high,
#             orb30_low=orb30_low,
#             rs_index=rs_index,
#             rs_industry=rs_industry,
#             slot_rel_vol=slot_rel_vol,
#             extended=extended,
#             reason_codes=reason_codes,
#             provider=provider,
#             volume_baseline=baseline,
#             trade_day=trade_day,
#             slot_at=slot_at,
#         )
#     return pulses
#
#
# def score_intraday_gate(
#     *,
#     snapshot: pd.DataFrame | None,
#     benchmark: pd.DataFrame | None,
#     pulses: Dict[str, SymbolPulse],
#     tracked_universe: TrackedUniverse,
#     data_complete: bool,
# ) -> SlotGate:
#     if not data_complete or benchmark is None or benchmark.empty or snapshot is None or snapshot.empty:
#         return SlotGate(state="UNAVAILABLE", score=0.0, reasons=["data_quality_incomplete"])
#
#     pct_col = "pct_chg" if "pct_chg" in snapshot.columns else ("chg" if "chg" in snapshot.columns else None)
#     if pct_col is None:
#         return SlotGate(state="UNAVAILABLE", score=0.0, reasons=["snapshot_columns_missing"])
#     pct = pd.to_numeric(snapshot[pct_col], errors="coerce").dropna()
#     if pct.empty:
#         return SlotGate(state="UNAVAILABLE", score=0.0, reasons=["snapshot_empty"])
#     up_ratio = float((pct > 0).mean())
#     mean_chg = float(pct.mean())
#     if up_ratio >= 0.58 and mean_chg > 0.3:
#         breadth_score = 100.0
#     elif up_ratio >= 0.50 and mean_chg > 0.0:
#         breadth_score = 70.0
#     elif up_ratio >= 0.42:
#         breadth_score = 45.0
#     else:
#         breadth_score = 20.0
#
#     benchmark_ret = _ret_from_open(benchmark)
#     benchmark_vwap, _ = _safe_vwap(benchmark)
#     benchmark_close = float(pd.to_numeric(benchmark["close"].iloc[-1], errors="coerce") or 0.0)
#     if benchmark_vwap is not None and benchmark_close > benchmark_vwap and benchmark_ret > 0:
#         benchmark_score = 100.0
#     elif benchmark_vwap is not None and benchmark_close > benchmark_vwap:
#         benchmark_score = 70.0
#     elif benchmark_ret > -0.003:
#         benchmark_score = 45.0
#     else:
#         benchmark_score = 20.0
#
#     reco_pulses = [pulses[symbol] for symbol in tracked_universe.reco if symbol in pulses]
#     median_slot_rel_vol = float(pd.Series([pulse.slot_rel_vol for pulse in reco_pulses if pulse.slot_rel_vol is not None]).median()) if reco_pulses else 0.0
#     if median_slot_rel_vol >= 0.9:
#         liquidity_score = 100.0
#     elif median_slot_rel_vol >= 0.7:
#         liquidity_score = 70.0
#     elif median_slot_rel_vol >= 0.5:
#         liquidity_score = 45.0
#     else:
#         liquidity_score = 20.0
#
#     buyable_count = sum(1 for pulse in reco_pulses if pulse.execution_state in BUY_STATES and not pulse.invalidated)
#     gate_score = 0.45 * breadth_score + 0.35 * benchmark_score + 0.20 * liquidity_score
#     if gate_score >= 60.0 and buyable_count >= 2:
#         state = "ALLOW"
#     elif gate_score >= 45.0 and buyable_count >= 1:
#         state = "DEGRADED"
#     elif buyable_count == 0 or gate_score < 45.0:
#         state = "BLOCKED"
#     else:
#         state = "UNAVAILABLE"
#     reasons = [
#         f"buyable_count={buyable_count}",
#         f"up_ratio={up_ratio:.3f}",
#         f"mean_chg={mean_chg:.3f}",
#         f"median_slot_rel_vol={median_slot_rel_vol:.3f}",
#     ]
#     return SlotGate(
#         state=state,
#         score=float(gate_score),
#         reasons=reasons,
#         breadth_score=float(breadth_score),
#         benchmark_score=float(benchmark_score),
#         liquidity_score=float(liquidity_score),
#         buyable_count=int(buyable_count),
#         metrics={
#             "up_ratio": up_ratio,
#             "mean_chg": mean_chg,
#             "benchmark_ret_open": benchmark_ret,
#             "benchmark_close": benchmark_close,
#             "benchmark_vwap": benchmark_vwap,
#             "median_slot_rel_vol": median_slot_rel_vol,
#         },
#     )
#
#
# def compute_slot_pulse_package(
#     *,
#     daybook: DayBook,
#     tracked_universe: TrackedUniverse,
#     trade_day: str,
#     slot_at: str,
#     previous_actions: Optional[Dict[str, str]] = None,
#     benchmark_symbol: Optional[str] = None,
# ) -> Dict[str, object]:
#     bundle = fetch_intraday_bundle(
#         trading_day=trade_day,
#         slot_at=slot_at,
#         symbols=tracked_universe.total,
#         benchmark_symbol=benchmark_symbol,
#     )
#     data_complete = (
#         bundle["symbols_received"] == bundle["symbols_expected"]
#         and bool(bundle["benchmark_received"])
#         and bundle.get("snapshot") is not None
#         and not bundle["snapshot"].empty
#     )
#     baselines = load_slot_volume_baselines(trade_day, tracked_universe.total)
#     provisional_gate = SlotGate(state="ALLOW", score=100.0, reasons=["pre_gate"])
#     provisional_pulses = evaluate_slot_pulses(
#         daybook=daybook,
#         tracked_universe=tracked_universe,
#         bars=bundle["bars"],
#         benchmark=bundle["benchmark"],
#         slot_baselines=baselines,
#         gate=provisional_gate,
#         slot_at=slot_at,
#         trade_day=trade_day,
#         provider=str(bundle["provider"]),
#         previous_actions=previous_actions,
#     )
#     gate = score_intraday_gate(
#         snapshot=bundle["snapshot"],
#         benchmark=bundle["benchmark"],
#         pulses=provisional_pulses,
#         tracked_universe=tracked_universe,
#         data_complete=bool(data_complete),
#     )
#     pulses = evaluate_slot_pulses(
#         daybook=daybook,
#         tracked_universe=tracked_universe,
#         bars=bundle["bars"],
#         benchmark=bundle["benchmark"],
#         slot_baselines=baselines,
#         gate=gate,
#         slot_at=slot_at,
#         trade_day=trade_day,
#         provider=str(bundle["provider"]),
#         previous_actions=previous_actions,
#     )
#     return {
#         "pulses": pulses,
#         "gate": gate,
#         "bundle": bundle,
#     }
#
#
# def apply_pulse(book, symbols: Iterable[str], *, target_trade_day: str | None, target_slot_at: str | None):
#     if not target_trade_day or not target_slot_at:
#         for symbol in symbols:
#             state = book.symbol_states.get(symbol)
#             if state is not None:
#                 state.is_stale = True
#                 state.stale_reason = "no_closed_bar_yet"
#                 state.execution_state = "unavailable"
#                 state.action = "INVALID"
#                 state.can_open = False
#         book.last_closed_5m = None
#         return book
#     tracked = TrackedUniverse(
#         reco=[pick.symbol for pick in book.daybook.picks],
#         reserve=[pick.symbol for pick in book.daybook.reserve_picks],
#         portfolio=[],
#         total=[str(symbol).strip() for symbol in symbols if str(symbol).strip()],
#     )
#     try:
#         pkg = compute_slot_pulse_package(
#             daybook=book.daybook,
#             tracked_universe=tracked,
#             trade_day=target_trade_day,
#             slot_at=target_slot_at,
#         )
#         pulses = pkg["pulses"]
#         for symbol, pulse in pulses.items():
#             book.symbol_states[symbol] = pulse
#         book.last_closed_5m = target_slot_at
#     except Exception as ex:  # noqa: BLE001
#         logger.warning("[pulse5m] wrapper apply_pulse failed trade_day=%s slot=%s error=%s", target_trade_day, target_slot_at, ex)
#         raise
#     return book
#
