from __future__ import annotations

from dataclasses import asdict
import os
from typing import Any, Callable, Dict, Iterable, List, Protocol, Tuple

import pandas as pd

from ..core.config import load_config
from ..core.logging import logger
from ..market_memory.retrieval import retrieve_similar_events
from ..market_memory.store import save_decision_snapshot, upsert_market_events
from ..probability_engine.engine import infer_probability
from ..providers.boards import is_mainboard
from ..providers.factory import get_provider
from ..providers.universe_provider import UniverseProvider
from ..risk_engine.engine import assess_candidate_risk, rank_candidate
from ..runtime.utils import now_iso
from ..selection_engine.datahub import MarketDataHub
from ..selection_engine.market_env import score_regime
from ..signal_engine.daily import build_signal_events_for_symbol
from .adaptive_policy import select_candidates
from .serenity_policy import FORMULA_VERSION, apply_serenity_addon, build_reference_snapshot
from ..serenity.models import FrozenSerenitySignal, SerenityPolicyState
from ..serenity.store import (
    load_frozen_signals,
    load_policy_state as load_serenity_policy_state,
    save_reference_and_enqueue_pending,
    suspend_policy,
)


class DailyDataSource(Protocol):
    def daily_ohlcv(
        self,
        symbol: str,
        as_of: str | None = None,
        min_len: int = 250,
        *,
        prefer_cache_only: bool = False,
        force_network: bool = False,
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]: ...


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _normalize_symbol(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if "." in raw:
        raw = raw.split(".", 1)[0]
    for prefix in ("sh", "sz", "bj"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else ""


def _has_positive_price(value: Any) -> bool:
    if isinstance(value, dict):
        for key in ("price", "low", "high", "trigger_price", "stop_price"):
            parsed = _safe_float(value.get(key), 0.0)
            if parsed > 0.0:
                return True
        return any(_has_positive_price(item) for item in (value.get("targets") or []))
    if isinstance(value, list):
        return any(_has_positive_price(item) for item in value)
    return _safe_float(value, 0.0) > 0.0


def _critical_candidate_reasons(candidate: Dict[str, Any], *, as_of: str) -> List[str]:
    reasons: List[str] = []
    symbol = _normalize_symbol(candidate.get("symbol") or candidate.get("code"))
    if len(symbol) != 6 or not symbol.isdigit():
        reasons.append("symbol_invalid")

    status = dict(candidate.get("data_status") or {})
    daily_meta = dict(status.get("daily_meta") or {})
    if status.get("ok") is not True:
        reasons.append("daily_data_invalid")
    rows = int(_safe_float(status.get("rows") or daily_meta.get("len"), 0.0))
    if rows < 120:
        reasons.append("daily_history_lt_120")
    last_date = _normalize_date(str(candidate.get("last_date") or status.get("as_of") or ""))
    if not last_date or last_date != _normalize_date(as_of):
        reasons.append("daily_bar_not_at_as_of")
    if daily_meta.get("strict_blocked") is True or str(daily_meta.get("freshness_state") or "") in {"missing", "stale", "failed_refresh"}:
        reasons.append("daily_cache_not_current")

    risk = dict(candidate.get("risk") or {})
    if not _has_positive_price(risk.get("entry")):
        reasons.append("entry_plan_missing")
    if not _has_positive_price(risk.get("stop")):
        reasons.append("stop_plan_missing")
    ranking_score = _safe_float((candidate.get("ranking") or {}).get("ranking_score"), float("nan"))
    if ranking_score != ranking_score or ranking_score in (float("inf"), float("-inf")):
        reasons.append("ranking_score_non_finite")
    return list(dict.fromkeys(reasons))


def _normalize_date(value: str) -> str:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _pick_col(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    cols = {str(col).strip().lower(): str(col) for col in df.columns}
    for cand in candidates:
        key = str(cand).strip().lower()
        if key in cols:
            return cols[key]
    return None


def _snapshot_universe(snapshot: pd.DataFrame | None, *, topk: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cfg = load_config()
    if snapshot is None or not isinstance(snapshot, pd.DataFrame) or snapshot.empty:
        return [], {"source": "snapshot", "ok": False, "reason": "snapshot_unavailable"}
    code_col = _pick_col(snapshot, ["code", "symbol", "ts_code", "代码"])
    if code_col is None:
        return [], {"source": "snapshot", "ok": False, "reason": "snapshot_code_missing", "columns": list(snapshot.columns)}
    name_col = _pick_col(snapshot, ["name", "名称"])
    industry_col = _pick_col(snapshot, ["industry", "行业"])
    amount_col = _pick_col(snapshot, ["amount", "turnover", "成交额", "成交额(元)"])
    close_col = _pick_col(snapshot, ["price", "close", "最新价"])
    rows: List[Dict[str, Any]] = []
    for _, row in snapshot.iterrows():
        code = _normalize_symbol(row.get(code_col))
        if not code or not is_mainboard(code):
            continue
        rows.append(
            {
                "code": code,
                "symbol": code,
                "name": str(row.get(name_col) or "").strip() if name_col else None,
                "industry": str(row.get(industry_col) or "").strip() if industry_col else None,
                "amount": _safe_float(row.get(amount_col)) if amount_col else 0.0,
                "price": _safe_float(row.get(close_col)) if close_col else 0.0,
            }
        )
    rows.sort(key=lambda item: _safe_float(item.get("amount")), reverse=True)
    try:
        limit = int(os.getenv("GP_MARKET_MEMORY_POOL_SIZE", "") or getattr(cfg, "dynamic_pool_size", 200) or 200)
    except Exception:
        limit = 200
    limit = max(int(topk) * 8, min(500, max(1, limit)))
    seen: set[str] = set()
    cleaned: List[Dict[str, Any]] = []
    for item in rows:
        code = str(item.get("code") or "")
        if code in seen:
            continue
        seen.add(code)
        cleaned.append(item)
        if len(cleaned) >= limit:
            break
    return cleaned, {
        "source": "snapshot",
        "ok": bool(cleaned),
        "input_count": int(len(snapshot)),
        "mainboard_count": len(rows),
        "output_count": len(cleaned),
        "limit": limit,
    }


def _file_universe(*, topk: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    provider = UniverseProvider()
    symbols = [symbol for symbol in provider.get_symbols() if is_mainboard(symbol)]
    try:
        limit = int(os.getenv("GP_UNIVERSE_MAX", "0") or 0)
    except Exception:
        limit = 0
    if limit <= 0:
        limit = max(int(topk) * 12, len(symbols))
    rows = [{"code": symbol, "symbol": symbol, "name": None, "industry": None, "amount": 0.0} for symbol in symbols[:limit]]
    meta = dict(provider.last_meta() or {})
    meta.update({"source": "universe:file", "output_count": len(rows), "limit": limit})
    return rows, meta


def _load_snapshot() -> Tuple[pd.DataFrame | None, Dict[str, Any]]:
    provider = get_provider()
    try:
        snapshot = provider.get_spot_snapshot()
        meta = getattr(provider, "last_snapshot_meta", lambda: {})() or {}
        if not isinstance(snapshot, pd.DataFrame) or snapshot.empty:
            return None, {**dict(meta), "ok": False, "reason": "snapshot_empty"}
        return snapshot, {**dict(meta), "ok": True, "rows": int(len(snapshot))}
    except Exception as ex:  # noqa: BLE001
        logger.warning("[market-memory] snapshot unavailable: %s", ex)
        return None, {"ok": False, "error": f"{type(ex).__name__}: {ex}"}


def _market_context(hub: MarketDataHub, snapshot: pd.DataFrame | None, snapshot_meta: Dict[str, Any]) -> Dict[str, Any]:
    try:
        env = score_regime(hub, snapshot=snapshot)
    except Exception as ex:  # noqa: BLE001
        env = {"grade": "C", "reasons": [f"market_regime_unavailable:{type(ex).__name__}"], "raw": {}}
    return {
        "market_regime": str(env.get("grade") or "C"),
        "grade": str(env.get("grade") or "C"),
        "regime_reasons": list(env.get("reasons") or []),
        "snapshot": snapshot_meta,
        "raw": dict(env.get("raw") or {}),
    }


def _compact_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    prob = candidate.get("probability") or {}
    evidence = prob.get("evidence") or {}
    risk = candidate.get("risk") or {}
    ranking = candidate.get("ranking") or {}
    adaptive = candidate.get("adaptive_policy") or {}
    return {
        "symbol": candidate.get("symbol"),
        "name": candidate.get("name"),
        "industry": candidate.get("industry"),
        "signal_type": candidate.get("signal_type"),
        "ranking_score": ranking.get("ranking_score"),
        "up_probability_3d": prob.get("up_probability_3d"),
        "expected_return_3d": prob.get("expected_return_3d"),
        "drawdown_probability": prob.get("drawdown_probability"),
        "uncertainty": prob.get("uncertainty"),
        "confidence": prob.get("confidence"),
        "effective_sample_size": evidence.get("effective_sample_size"),
        "mean_similarity": evidence.get("mean_similarity"),
        "sample_size": evidence.get("sample_size"),
        "risk_flags": list(risk.get("risk_flags") or []),
        "adaptive_score": adaptive.get("adaptive_score") or candidate.get("adaptive_score"),
        "decision_score": (
            adaptive.get("decision_score")
            if adaptive.get("decision_score") is not None
            else candidate.get("decision_score")
            if candidate.get("decision_score") is not None
            else adaptive.get("adaptive_score")
            if adaptive.get("adaptive_score") is not None
            else candidate.get("adaptive_score")
        ),
        "calibrated_probability": adaptive.get("calibrated_probability") or candidate.get("calibrated_probability"),
        "recommendation_strength": adaptive.get("recommendation_strength") or candidate.get("recommendation_strength"),
        "adaptive_action": adaptive.get("action") or candidate.get("adaptive_action"),
        "feature_coverage": adaptive.get("feature_coverage") or candidate.get("feature_coverage"),
        "expert_scores": dict(adaptive.get("expert_scores") or candidate.get("expert_scores") or {}),
        "expert_contributions": dict(adaptive.get("expert_contributions") or candidate.get("expert_contributions") or {}),
        "missing_features": list(adaptive.get("missing_features") or candidate.get("missing_features") or []),
        "reason_codes": list(candidate.get("reason_codes") or []),
        "rejected_reason": candidate.get("rejected_reason"),
        "serenity_reference": {
            "status": adaptive.get("serenity_status") or candidate.get("serenity_status") or "not_ready",
            "policy_state": adaptive.get("serenity_policy_state") or candidate.get("serenity_policy_state") or "warming",
            "weight": adaptive.get("serenity_weight") if adaptive.get("serenity_weight") is not None else candidate.get("serenity_weight", 0.0),
            "adjustment": adaptive.get("serenity_adjustment") if adaptive.get("serenity_adjustment") is not None else candidate.get("serenity_adjustment", 0.0),
            "fact_ids": list(adaptive.get("serenity_fact_ids") or candidate.get("serenity_fact_ids") or [])[:5],
            "non_binding": bool(adaptive.get("serenity_non_binding", candidate.get("serenity_non_binding", True))),
        },
    }


def _trade_plan_from_risk(risk: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "entry": dict(risk.get("entry") or {}),
        "stop": dict(risk.get("stop") or {}),
        "take_profit": dict(risk.get("take_profit") or {}),
        "diagnostics": dict(risk.get("diagnostics") or {}),
    }


def _candidate_text(candidate: Dict[str, Any]) -> str:
    prob = candidate.get("probability") or {}
    evidence = prob.get("evidence") or {}
    return (
        f"{candidate.get('signal_type')}：相似案例 {evidence.get('sample_size', 0)} 个，"
        f"有效样本 {float(evidence.get('effective_sample_size') or 0.0):.1f}，"
        f"3日上涨概率 {float(prob.get('up_probability_3d') or 0.0) * 100:.1f}%，"
        f"期望收益 {float(prob.get('expected_return_3d') or 0.0) * 100:.2f}%。"
    )


def _render_adaptive_narrative(snapshot: Dict[str, Any]) -> str:
    decision = str(snapshot.get("final_decision") or "no_trade")
    selected = [str(symbol) for symbol in (snapshot.get("selected_symbols") or [])]
    adaptive = dict(snapshot.get("adaptive_policy_output") or {})
    candidates = list(adaptive.get("adaptive_candidates") or [])
    if decision != "recommend" or not selected:
        debug = dict(adaptive.get("policy_debug") or {})
        reason = str(debug.get("reason") or "no_ranked_candidates")
        return f"当前没有生成可发布推荐：{reason}。"
    top = next((item for item in candidates if str(item.get("symbol")) in selected), candidates[0] if candidates else {})
    symbol = str(top.get("symbol") or selected[0])
    contributions = dict(top.get("expert_contributions") or {})
    ranked_contrib = sorted(contributions.items(), key=lambda kv: abs(float(kv[1] or 0.0)), reverse=True)[:3]
    contribution_text = "、".join(f"{key}:{float(value):+.3f}" for key, value in ranked_contrib) or "adaptive_policy"
    missing = list(top.get("missing_features") or [])[:3]
    reasons = list(top.get("reason_codes") or [])[:4]
    missing_text = "；缺失特征 " + "、".join(missing) if missing else ""
    reason_text = "；原因码 " + "、".join(reasons) if reasons else ""
    strength = str(top.get("recommendation_strength") or "normal")
    action_text = "探索性推荐/谨慎跟踪" if strength in {"cautious", "exploratory"} else "进入推荐"
    return (
        f"{symbol} {action_text}：adaptive_score {float(top.get('adaptive_score') or 0.0):.3f}，"
        f"strength {strength}，校准上涨概率 {float(top.get('calibrated_probability') or 0.0) * 100:.1f}%，"
        f"confidence {float(top.get('confidence') or 0.0):.2f}，"
        f"uncertainty {float(top.get('uncertainty') or 0.0):.2f}，"
        f"主要贡献 {contribution_text}{missing_text}{reason_text}。"
    )


def run_market_memory_selection(
    *,
    date: str,
    topk: int = 10,
    risk_profile: str = "normal",
    symbols: List[str] | None = None,
    prefer_cache_only: bool = False,
    allow_snapshot: bool = True,
    data_source: DailyDataSource | None = None,
    market_context_override: Dict[str, Any] | None = None,
    policy_state: Dict[str, Any] | None = None,
    historical_market_context_resolver: Callable[[str], Dict[str, Any]] | None = None,
    historical_event_mode: str = "window",
    serenity_signal_source: Callable[..., Dict[str, FrozenSerenitySignal]] | None = None,
    serenity_mode: str | None = None,
    serenity_policy_state: Any | None = None,
    serenity_persist: bool = True,
) -> Dict[str, Any]:
    date = _normalize_date(date)
    hub: DailyDataSource = data_source or MarketDataHub()
    symbols = [_normalize_symbol(symbol) for symbol in (symbols or [])]
    symbols = [symbol for symbol in symbols if symbol and is_mainboard(symbol)]
    if symbols:
        snapshot, snapshot_meta = None, {"ok": False, "reason": "historical_symbols_mode"}
    elif allow_snapshot:
        snapshot, snapshot_meta = _load_snapshot()
    else:
        snapshot, snapshot_meta = None, {"ok": False, "reason": "snapshot_disabled_daily_mode", "time_travel_safe": True}
    market_context = dict(market_context_override or _market_context(hub, snapshot, snapshot_meta))
    market_context.setdefault("market_regime", str(market_context.get("grade") or "C"))
    market_context.setdefault("grade", str(market_context.get("market_regime") or "C"))
    market_context["as_of"] = date
    if symbols:
        universe = [{"code": symbol, "symbol": symbol, "name": None, "industry": None, "amount": 0.0} for symbol in symbols]
        universe_meta = {"source": "symbols:param", "output_count": len(universe), "time_travel_safe": True}
    else:
        universe, universe_meta = _snapshot_universe(snapshot, topk=topk)
    if not universe and not symbols:
        universe, universe_meta = _file_universe(topk=topk)

    signals: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    all_historical = []
    for item in universe:
        symbol = str(item.get("symbol") or item.get("code") or "").strip()
        if not symbol:
            continue
        try:
            df, data_meta = hub.daily_ohlcv(symbol, as_of=date, min_len=120, prefer_cache_only=prefer_cache_only)
            signal_kwargs: Dict[str, Any] = {
                "symbol": symbol,
                "df": df,
                "as_of": date,
                "name": item.get("name"),
                "industry": item.get("industry"),
                "market_context": market_context,
                "max_history": 90,
            }
            if historical_market_context_resolver is not None:
                signal_kwargs["historical_market_context_resolver"] = historical_market_context_resolver
            if historical_event_mode != "window":
                signal_kwargs["historical_event_mode"] = historical_event_mode
            signal_result = build_signal_events_for_symbol(**signal_kwargs)
            if signal_result.current_event is None:
                failures.append({"symbol": symbol, "stage": "signal", "reason": signal_result.data_status.get("reason")})
                continue
            all_historical.extend(signal_result.historical_events)
            signals.append(
                {
                    "universe_item": item,
                    "current_event": signal_result.current_event,
                    "last_close": signal_result.last_close,
                    "last_date": signal_result.last_date,
                    "data_status": {**signal_result.data_status, "daily_meta": data_meta},
                }
            )
        except Exception as ex:  # noqa: BLE001
            failures.append({"symbol": symbol, "stage": "daily", "error": f"{type(ex).__name__}: {ex}"})

    upserted_events = upsert_market_events(all_historical)

    candidates: List[Dict[str, Any]] = []
    for row in signals:
        current_event = row["current_event"]
        retrieval = retrieve_similar_events(current_event, as_of=date, k=80, max_pool=6000)
        event_dict = asdict(current_event)
        probability = infer_probability(current_event=event_dict, retrieval=retrieval)
        signal = {
            "event_id": current_event.event_id,
            "signal_type": current_event.signal_type,
            "features": dict(current_event.features or {}),
            "feature_vector": dict(current_event.feature_vector or {}),
            "market_context": dict(current_event.market_context or {}),
            "retrieval_method": retrieval.get("retrieval_method"),
        }
        risk = assess_candidate_risk(signal=signal, probability=probability)
        ranking = rank_candidate(probability=probability, risk=risk)
        item = dict(row.get("universe_item") or {})
        symbol = current_event.symbol
        text = _candidate_text({"signal_type": current_event.signal_type, "probability": probability})
        candidate = {
            "symbol": symbol,
            "code": symbol,
            "name": item.get("name") or (current_event.features or {}).get("name"),
            "industry": item.get("industry") or (current_event.features or {}).get("industry"),
            "signal_type": current_event.signal_type,
            "signal": signal,
            "probability": probability,
            "risk": risk,
            "ranking": ranking,
            "historical_cases": list((probability.get("evidence") or {}).get("nearest_cases") or []),
            "final_score": float(ranking.get("ranking_score") or 0.0),
            "ranking_score": float(ranking.get("ranking_score") or 0.0),
            "trade_plan": _trade_plan_from_risk(risk),
            "risk_flags": list(risk.get("risk_flags") or []),
            "reason_codes": ["market_memory_similarity", "bayesian_probability", "risk_adjusted_ranking"],
            "user_thesis": text,
            "why_selected_text": text,
            "last_close": row.get("last_close"),
            "last_date": row.get("last_date"),
            "data_status": row.get("data_status") or {},
        }
        critical_reasons = _critical_candidate_reasons(candidate, as_of=date)
        if critical_reasons:
            candidate["hard_block"] = True
            candidate["hard_block_reasons"] = critical_reasons
            candidate["reason_codes"] = [*candidate["reason_codes"], *critical_reasons]
        candidates.append(candidate)

    candidates.sort(key=lambda item: float((item.get("ranking") or {}).get("ranking_score") or 0.0), reverse=True)
    ranked = candidates[: max(int(topk) * 3, int(topk))]
    adaptive_input = {
        "as_of": date,
        "risk_profile": risk_profile,
        "market_context": market_context,
        "ranked_candidates": [_compact_candidate(item) for item in ranked[: max(10, int(topk))]],
        "permission_boundary": {
            "selection_authority": "adaptive_policy",
            "llm_role": "not_used_for_selection",
            "allowed_decisions": ["recommend", "no_trade"],
            "risk_is_penalty_not_gate": True,
            "missing_data_is_feature": True,
            "cannot_promote_outside_math_ranking": True,
        },
    }
    adaptive = select_candidates(
        ranked,
        topk=topk,
        market_context=market_context,
        risk_profile=risk_profile,
        state=policy_state,
    )
    decision_created_at = now_iso()
    serenity_cfg = load_config().serenity
    resolved_serenity_mode = str(serenity_mode or serenity_cfg.mode)
    serenity_state = serenity_policy_state
    if serenity_state is None:
        serenity_state = (
            SerenityPolicyState(
                state="off",
                applied_weight=0.0,
                max_weight=serenity_cfg.max_weight,
                state_since=decision_created_at,
                updated_at=decision_created_at,
            )
            if resolved_serenity_mode == "off"
            else load_serenity_policy_state()
        )
    serenity_symbols = [str(item.get("symbol") or item.get("code") or "") for item in (adaptive.get("adaptive_candidates") or [])]
    serenity_signals: Dict[str, FrozenSerenitySignal] = {}
    if resolved_serenity_mode != "off" and serenity_symbols:
        resolver = serenity_signal_source or load_frozen_signals
        try:
            serenity_signals = dict(resolver(serenity_symbols, decision_at=decision_created_at) or {})
        except Exception as ex:  # noqa: BLE001
            logger.warning("[serenity] local signal resolution failed: %s", ex)
            serenity_signals = {}
    future_evidence_detected = any(
        any(
            str(limitation).startswith("future_timestamp_evidence_excluded:")
            for limitation in signal.limitations
        )
        for signal in serenity_signals.values()
    )
    if future_evidence_detected and resolved_serenity_mode == "auto":
        try:
            serenity_state = (
                suspend_policy("future_dated_serenity_evidence_detected")
                if serenity_persist
                else serenity_state.model_copy(
                    update={
                        "state": "suspended",
                        "applied_weight": 0.0,
                        "suspension_reasons": ["future_dated_serenity_evidence_detected"],
                    }
                )
            )
        except Exception as ex:  # noqa: BLE001
            logger.error("[serenity] failed to persist future-evidence suspension: %s", ex)
            serenity_state = serenity_state.model_copy(
                update={
                    "state": "suspended",
                    "applied_weight": 0.0,
                    "suspension_reasons": ["future_dated_serenity_evidence_detected"],
                }
            )
    adaptive = apply_serenity_addon(
        adaptive,
        serenity_signals,
        serenity_state,
        topk=topk,
        mode=resolved_serenity_mode,
    )
    adaptive_by_symbol = {str(item.get("symbol")): item for item in (adaptive.get("adaptive_candidates") or [])}
    for item in ranked:
        symbol = str(item.get("symbol") or item.get("code") or "")
        scored = dict(adaptive_by_symbol.get(symbol) or {})
        if not scored:
            continue
        item["adaptive_policy"] = scored
        item["adaptive_score"] = float(scored.get("adaptive_score") or 0.0)
        item["decision_score"] = float(scored.get("decision_score") if scored.get("decision_score") is not None else scored.get("adaptive_score") or 0.0)
        item["calibrated_probability"] = float(scored.get("calibrated_probability") or 0.0)
        item["recommendation_strength"] = str(scored.get("recommendation_strength") or "")
        item["adaptive_action"] = str(scored.get("action") or "")
        item["feature_coverage"] = float(scored.get("feature_coverage") or 0.0)
        item["expert_scores"] = dict(scored.get("expert_scores") or {})
        item["expert_contributions"] = dict(scored.get("expert_contributions") or {})
        item["missing_features"] = list(scored.get("missing_features") or [])
        item["serenity_adjustment"] = float(scored.get("serenity_adjustment") or 0.0)
        item["serenity_status"] = str(scored.get("serenity_status") or "not_ready")
        item["serenity_fact_ids"] = list(scored.get("serenity_fact_ids") or [])
        item["serenity_learning_eligible"] = bool(scored.get("serenity_learning_eligible"))
        item["serenity_policy_state"] = str(scored.get("serenity_policy_state") or serenity_state.state)
        item["serenity_weight"] = float(scored.get("serenity_weight") or 0.0)
        item["serenity_non_binding"] = bool(scored.get("serenity_non_binding", True))
        item["serenity_would_change_topk"] = bool(
            scored.get("serenity_would_change_topk")
        )
        item["serenity_reference_would_change_topk"] = bool(
            scored.get("serenity_reference_would_change_topk")
        )
        merged_reasons = [*list(item.get("reason_codes") or []), *list(scored.get("reason_codes") or [])]
        item["reason_codes"] = list(dict.fromkeys(str(reason) for reason in merged_reasons if str(reason)))
        item["final_score"] = float(scored.get("decision_score") if scored.get("decision_score") is not None else scored.get("adaptive_score") or item.get("final_score") or 0.0)
    applied_serenity_weight = float((adaptive.get("serenity_policy") or {}).get("applied_weight") or 0.0)
    if applied_serenity_weight > 0.0:
        # Shadow must remain byte-for-byte equivalent to the baseline ordering.  Once
        # promoted, the complete ranked view follows the already-frozen add-on order;
        # candidates rejected by the baseline hard-block checks remain at the tail.
        serenity_order = {
            str(item.get("symbol") or ""): index
            for index, item in enumerate(adaptive.get("adaptive_candidates") or [])
        }
        baseline_order = {str(item.get("symbol") or item.get("code") or ""): index for index, item in enumerate(ranked)}
        ranked.sort(
            key=lambda item: (
                serenity_order.get(str(item.get("symbol") or item.get("code") or ""), 10**9),
                baseline_order.get(str(item.get("symbol") or item.get("code") or ""), 10**9),
                str(item.get("symbol") or item.get("code") or ""),
            )
        )
    selected_symbols_ordered = [str(symbol) for symbol in (adaptive.get("selected_symbols") or []) if str(symbol)]
    selected_symbols = set(selected_symbols_ordered)
    final_decision = str(adaptive.get("final_decision") or "no_trade")
    ranked_by_symbol = {str(item.get("symbol")): item for item in ranked}
    picks = [ranked_by_symbol[symbol] for symbol in selected_symbols_ordered if symbol in ranked_by_symbol][:topk]
    rejected = [item for item in ranked if str(item.get("symbol")) not in selected_symbols][: max(20, topk * 3)]
    for item in rejected:
        item["rejected_reason"] = "not_in_adaptive_topk" if final_decision == "recommend" else f"decision_{final_decision}"

    snapshot_payload = {
        "schema": "DecisionContextSnapshot.v1",
        "run_id": f"market_memory_{date}_{now_iso()}",
        "as_of": date,
        "created_at": decision_created_at,
        "market_context": market_context,
        "candidate_list": [_compact_candidate(item) for item in ranked],
        "rejected_candidates": [_compact_candidate(item) for item in rejected],
        "historical_cases": {
            str(item.get("symbol")): list(item.get("historical_cases") or [])[:8]
            for item in ranked[: max(10, topk)]
        },
        "probability_output": {str(item.get("symbol")): item.get("probability") for item in ranked[: max(10, topk)]},
        "risk_output": {str(item.get("symbol")): item.get("risk") for item in ranked[: max(10, topk)]},
        "serenity_outcome_risk_plans": {
            str(item.get("symbol")): item.get("risk")
            for item in ranked
            if str(item.get("symbol") or "")
        },
        "ranking_output": {
            "method": "adaptive_score_topk_no_low_sample_gate",
            "ranked_symbols": [str(item.get("symbol")) for item in ranked],
            "details": {str(item.get("symbol")): item.get("ranking") for item in ranked[: max(10, topk)]},
        },
        "adaptive_policy_input": adaptive_input,
        "adaptive_policy_output": adaptive,
        "adaptive_policy_state_version": adaptive.get("policy_state_version"),
        "serenity_policy_snapshot": dict(adaptive.get("serenity_policy") or {}),
        "reference_signal_output": {
            symbol: {
                "status": signal.status,
                "availability": signal.availability,
                "learning_eligible": signal.learning_eligible,
                "direction": signal.direction,
                "confidence": signal.confidence,
                "source_quality": signal.source_quality,
                "fact_ids": list(signal.fact_ids),
                "hypothesis_ids": list(signal.hypothesis_ids),
                "input_hash": signal.input_hash,
                "decision_at": signal.decision_at,
                "limitations": list(signal.limitations),
            }
            for symbol, signal in serenity_signals.items()
        },
        "serenity_counterfactuals": list(adaptive.get("serenity_counterfactuals") or []),
        "serenity_reference_counterfactuals": list(adaptive.get("serenity_reference_counterfactuals") or []),
        "calibration_output": {
            str(item.get("symbol")): (item.get("adaptive_policy") or {}).get("calibration")
            for item in ranked[: max(10, topk)]
        },
        "llm_decision_input": {"source": "not_used_for_selection", "reason": "selection_owned_by_adaptive_policy"},
        "llm_input_context": {"source": "not_used_for_selection", "reason": "selection_owned_by_adaptive_policy"},
        "llm_decision_json": {"source": "not_used_for_selection", "reason": "selection_owned_by_adaptive_policy"},
        "validator_result": adaptive.get("validator_result") or {},
        "narrator_input": {
            "final_decision": final_decision,
            "selected_symbols": selected_symbols_ordered,
            "candidate_count": len(ranked),
        },
        "final_decision": final_decision,
        "selected_symbols": selected_symbols_ordered,
    }
    snapshot_payload["final_response"] = _render_adaptive_narrative(snapshot_payload)
    snapshot_id = save_decision_snapshot(snapshot_payload)
    serenity_reference_snapshot_id = None
    if serenity_persist and resolved_serenity_mode != "off" and serenity_signals:
        try:
            reference_snapshot = build_reference_snapshot(
                decision_context_snapshot_id=snapshot_id,
                decision_day=date,
                decision_at=decision_created_at,
                adaptive_output=adaptive,
                signals=serenity_signals,
                risk_plans=dict(snapshot_payload.get("serenity_outcome_risk_plans") or {}),
            )
            serenity_reference_snapshot_id, _ = save_reference_and_enqueue_pending(
                reference_snapshot,
                decision_day=date,
                epoch=serenity_state.epoch,
                formula_version=FORMULA_VERSION,
            )
            snapshot_payload["serenity_reference_snapshot_id"] = serenity_reference_snapshot_id
            save_decision_snapshot(snapshot_payload)
        except Exception as ex:  # noqa: BLE001
            if applied_serenity_weight > 0.0:
                try:
                    suspend_policy("binding_reference_persistence_failed")
                finally:
                    raise RuntimeError("serenity_binding_reference_persistence_failed") from ex
            logger.warning("[serenity] reference snapshot persistence failed: %s", ex)

    for item in picks + rejected:
        item["decision_context_snapshot_id"] = snapshot_id
        if serenity_reference_snapshot_id:
            item["serenity_reference_snapshot_id"] = serenity_reference_snapshot_id

    return {
        "as_of": date,
        "timezone": load_config().timezone,
        "env": market_context,
        "market_context": market_context,
        "candidate_pool": ranked,
        "rejected_candidates": rejected,
        "picks": picks,
        "tradeable": bool(final_decision == "recommend" and picks),
        "decision": final_decision,
        "reason": final_decision,
        "message": snapshot_payload["final_response"],
        "decision_context_snapshot_id": snapshot_id,
        "serenity_reference_snapshot_id": serenity_reference_snapshot_id,
        "adaptive_policy": adaptive,
        "debug": {
            "pipeline": "market_memory_adaptive_v1",
            "universe": universe_meta,
            "snapshot": snapshot_meta,
            "signals_count": len(signals),
            "candidate_count": len(candidates),
            "market_memory_events_upserted": upserted_events,
            "failures": failures[:50],
            "adaptive_single_path": True,
            "selection_policy": "adaptive_policy_single_path",
        },
    }
