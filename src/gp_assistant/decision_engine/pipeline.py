from __future__ import annotations

from dataclasses import asdict
import os
from typing import Any, Dict, Iterable, List, Tuple

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
from .risk_committee import render_narrative_from_validated_decision, run_risk_committee


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


def run_market_memory_selection(
    *,
    date: str,
    topk: int = 10,
    risk_profile: str = "normal",
    symbols: List[str] | None = None,
    prefer_cache_only: bool = False,
) -> Dict[str, Any]:
    date = _normalize_date(date)
    hub = MarketDataHub()
    symbols = [_normalize_symbol(symbol) for symbol in (symbols or [])]
    symbols = [symbol for symbol in symbols if symbol and is_mainboard(symbol)]
    snapshot, snapshot_meta = (None, {"ok": False, "reason": "historical_symbols_mode"}) if symbols else _load_snapshot()
    market_context = _market_context(hub, snapshot, snapshot_meta)
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
            signal_result = build_signal_events_for_symbol(
                symbol=symbol,
                df=df,
                as_of=date,
                name=item.get("name"),
                industry=item.get("industry"),
                market_context=market_context,
                max_history=90,
            )
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
        candidates.append(candidate)

    candidates.sort(key=lambda item: float((item.get("ranking") or {}).get("ranking_score") or 0.0), reverse=True)
    ranked = candidates[: max(int(topk) * 3, int(topk))]
    decision_input = {
        "as_of": date,
        "risk_profile": risk_profile,
        "market_context": market_context,
        "ranked_candidates": [_compact_candidate(item) for item in ranked[: max(10, int(topk))]],
        "permission_boundary": {
            "llm_role": "risk_committee",
            "allowed_decisions": ["recommend", "observe", "no_trade"],
            "can_only_downgrade": True,
            "cannot_promote_outside_math_ranking": True,
        },
    }
    validator = run_risk_committee(decision_input, ranked)
    selected_symbols = set(str(symbol) for symbol in (validator.get("selected_symbols") or []))
    final_decision = str(validator.get("final_decision") or "no_trade")
    if final_decision != "recommend":
        selected_symbols = set()
    picks = [item for item in ranked if str(item.get("symbol")) in selected_symbols][:topk]
    rejected = [item for item in ranked if str(item.get("symbol")) not in selected_symbols][: max(20, topk * 3)]
    for item in rejected:
        item["rejected_reason"] = "risk_committee_not_selected" if final_decision == "recommend" else f"decision_{final_decision}"

    snapshot_payload = {
        "schema": "DecisionContextSnapshot.v1",
        "run_id": f"market_memory_{date}_{now_iso()}",
        "as_of": date,
        "created_at": now_iso(),
        "market_context": market_context,
        "candidate_list": [_compact_candidate(item) for item in ranked],
        "rejected_candidates": [_compact_candidate(item) for item in rejected],
        "historical_cases": {
            str(item.get("symbol")): list(item.get("historical_cases") or [])[:8]
            for item in ranked[: max(10, topk)]
        },
        "probability_output": {str(item.get("symbol")): item.get("probability") for item in ranked[: max(10, topk)]},
        "risk_output": {str(item.get("symbol")): item.get("risk") for item in ranked[: max(10, topk)]},
        "ranking_output": {
            "method": "expected_return_x_win_probability_x_execution_quality_x_confidence_x_risk_adjustment",
            "ranked_symbols": [str(item.get("symbol")) for item in ranked],
            "details": {str(item.get("symbol")): item.get("ranking") for item in ranked[: max(10, topk)]},
        },
        "llm_decision_input": decision_input,
        "llm_input_context": decision_input,
        "llm_decision_json": (validator.get("llm_decision") or {}),
        "validator_result": validator,
        "narrator_input": {
            "final_decision": final_decision,
            "selected_symbols": list(selected_symbols),
            "candidate_count": len(ranked),
        },
        "final_decision": final_decision,
        "selected_symbols": list(selected_symbols),
    }
    snapshot_payload["final_response"] = render_narrative_from_validated_decision(snapshot_payload)
    snapshot_id = save_decision_snapshot(snapshot_payload)

    for item in picks + rejected:
        item["decision_context_snapshot_id"] = snapshot_id

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
        "debug": {
            "pipeline": "market_memory_v1",
            "universe": universe_meta,
            "snapshot": snapshot_meta,
            "signals_count": len(signals),
            "candidate_count": len(candidates),
            "market_memory_events_upserted": upserted_events,
            "failures": failures[:50],
            "old_scoring_disabled": True,
        },
    }
