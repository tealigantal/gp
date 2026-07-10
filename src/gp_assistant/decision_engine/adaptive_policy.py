from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..core.paths import store_dir
from ..runtime.utils import now_iso


POLICY_SCHEMA = "AdaptiveDecisionPolicy.v1"
DEFAULT_POLICY_NAME = "adaptive_decision"
EXPERT_KEYS = ("signal", "memory", "probability", "risk", "setup", "ranking", "regime", "exploration")
DEFAULT_WEIGHTS = {
    "signal": 0.16,
    "memory": 0.14,
    "probability": 0.20,
    "risk": 0.16,
    "setup": 0.14,
    "ranking": 0.12,
    "regime": 0.05,
    "exploration": 0.03,
}
MIN_WEIGHT = 0.03
MAX_WEIGHT = 0.45


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _float_or_none(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0, default: float = 0.0) -> float:
    out = _safe_float(value, default)
    return lo if out < lo else hi if out > hi else out


def _nested(obj: Dict[str, Any], path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _normalize_symbol(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "." in raw:
        raw = raw.split(".", 1)[0]
    lower = raw.lower()
    for prefix in ("sh", "sz", "bj"):
        if lower.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else str(value or "").strip()


def _project_weights(weights: Dict[str, Any]) -> Dict[str, float]:
    raw = {key: max(0.0, _safe_float(weights.get(key), DEFAULT_WEIGHTS[key])) for key in EXPERT_KEYS}
    fixed: Dict[str, float] = {}
    free = set(EXPERT_KEYS)
    for _ in range(len(EXPERT_KEYS) + 2):
        remaining = 1.0 - sum(fixed.values())
        if remaining <= 0.0 or not free:
            break
        base_total = sum(raw[key] for key in free)
        if base_total <= 0.0:
            assigned = {key: remaining / len(free) for key in free}
        else:
            assigned = {key: remaining * raw[key] / base_total for key in free}
        changed = False
        for key, value in list(assigned.items()):
            if value < MIN_WEIGHT:
                fixed[key] = MIN_WEIGHT
                free.remove(key)
                changed = True
            elif value > MAX_WEIGHT:
                fixed[key] = MAX_WEIGHT
                free.remove(key)
                changed = True
        if not changed:
            fixed.update(assigned)
            free.clear()
            break
    if free:
        remaining = max(0.0, 1.0 - sum(fixed.values()))
        each = remaining / max(1, len(free))
        for key in free:
            fixed[key] = _clamp(each, MIN_WEIGHT, MAX_WEIGHT, DEFAULT_WEIGHTS[key])
    total = sum(fixed.values())
    if total <= 0.0:
        return dict(DEFAULT_WEIGHTS)
    out = {key: _clamp(fixed.get(key, DEFAULT_WEIGHTS[key]) / total, MIN_WEIGHT, MAX_WEIGHT, DEFAULT_WEIGHTS[key]) for key in EXPERT_KEYS}
    total = sum(out.values())
    if abs(total - 1.0) > 1e-9:
        out = {key: value / total for key, value in out.items()}
    return out


def initial_policy_state() -> dict:
    return {
        "schema": POLICY_SCHEMA,
        "version": 1,
        "updated_at": now_iso(),
        "expert_weights": _project_weights(DEFAULT_WEIGHTS),
        "calibration": {},
        "feature_stats": {},
        "update_count": 0,
        "last_update_meta": {},
    }


def _policy_state_path(policy_name: str = DEFAULT_POLICY_NAME) -> Path:
    root = Path(os.getenv("GP_MARKET_MEMORY_DIR") or str(store_dir() / "events"))
    path = root / "policy_states"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{policy_name}.json"


def _normalize_state(state: dict | None) -> dict:
    base = initial_policy_state()
    if not isinstance(state, dict):
        return base
    base.update({key: value for key, value in state.items() if key not in {"expert_weights"}})
    base["schema"] = POLICY_SCHEMA
    base["version"] = int(_safe_float(state.get("version"), 1))
    base["expert_weights"] = _project_weights(dict(state.get("expert_weights") or DEFAULT_WEIGHTS))
    base["calibration"] = dict(state.get("calibration") or {})
    base["feature_stats"] = dict(state.get("feature_stats") or {})
    base["last_update_meta"] = dict(state.get("last_update_meta") or {})
    base["update_count"] = int(_safe_float(state.get("update_count"), 0))
    return base


def load_policy_state(policy_name: str = DEFAULT_POLICY_NAME) -> dict:
    path = _policy_state_path(policy_name)
    if not path.exists():
        return initial_policy_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return initial_policy_state()
    return _normalize_state(raw)


def save_policy_state(state: dict, policy_name: str = DEFAULT_POLICY_NAME) -> None:
    normalized = _normalize_state(state)
    normalized["updated_at"] = now_iso()
    path = _policy_state_path(policy_name)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _feature(name: str, value: Any, *, source: str, prior: float, quality: float = 1.0) -> Dict[str, Any]:
    parsed = _float_or_none(value)
    available = parsed is not None
    return {
        "name": name,
        "value": float(parsed if available else prior),
        "available": bool(available),
        "quality": float(_clamp(quality if available else 0.0, 0.0, 1.0)),
        "missing": not available,
        "source": source,
    }


def _enum_feature(name: str, value: Any, *, source: str, mapping: Dict[str, float], prior: float = 0.5) -> Dict[str, Any]:
    text = str(value or "").strip()
    available = bool(text)
    return {
        "name": name,
        "value": float(mapping.get(text.lower(), mapping.get(text.upper(), prior))) if available else float(prior),
        "available": available,
        "quality": 1.0 if available else 0.0,
        "missing": not available,
        "source": source,
        "raw": text,
    }


def _collection_feature(name: str, value: Any, *, source: str) -> Dict[str, Any]:
    available = isinstance(value, (list, dict))
    count = len(value) if isinstance(value, (list, dict)) else 0
    return {
        "name": name,
        "value": float(min(1.0, count / 5.0)),
        "available": available,
        "quality": 1.0 if available else 0.0,
        "missing": not available,
        "source": source,
        "raw": value if available else ([] if isinstance(value, list) else {}),
    }


def _has_price(obj: Any) -> bool:
    if isinstance(obj, dict):
        if _float_or_none(obj.get("price")) is not None:
            return True
        if _float_or_none(obj.get("low")) is not None and _float_or_none(obj.get("high")) is not None:
            return True
        targets = obj.get("targets")
        return isinstance(targets, list) and any(_float_or_none(item) is not None for item in targets)
    if isinstance(obj, list):
        return any(_float_or_none(item) is not None for item in obj)
    return _float_or_none(obj) is not None


def build_missing_aware_features(candidate: dict, market_context: dict) -> dict:
    candidate = dict(candidate or {})
    market_context = dict(market_context or {})
    probability = dict(candidate.get("probability") or {})
    evidence = dict(probability.get("evidence") or {})
    risk = dict(candidate.get("risk") or {})
    risk_diag = dict(risk.get("diagnostics") or {})
    ranking = dict(candidate.get("ranking") or {})
    ranking_factors = dict(ranking.get("ranking_factors") or {})
    signal = dict(candidate.get("signal") or {})
    signal_features = dict(signal.get("features") or {})
    signal_vector = dict(signal.get("feature_vector") or {})

    features: Dict[str, Dict[str, Any]] = {}

    def add(name: str, value: Any, *, source: str, prior: float, quality: float = 1.0) -> None:
        features[name] = _feature(name, value, source=source, prior=prior, quality=quality)

    add("probability.up_probability_3d", probability.get("up_probability_3d"), source="probability", prior=0.5)
    add("probability.expected_return_3d", probability.get("expected_return_3d"), source="probability", prior=0.0)
    add("probability.drawdown_probability", probability.get("drawdown_probability"), source="probability", prior=0.5)
    add("probability.expected_max_drawdown", probability.get("expected_max_drawdown"), source="probability", prior=0.03)
    add("probability.uncertainty", probability.get("uncertainty"), source="probability", prior=0.35)
    add("probability.confidence", probability.get("confidence"), source="probability", prior=0.5)
    add("probability.evidence.sample_size", evidence.get("sample_size"), source="probability", prior=0.0)
    add("probability.evidence.effective_sample_size", evidence.get("effective_sample_size"), source="probability", prior=0.0)
    add("probability.evidence.mean_similarity", evidence.get("mean_similarity"), source="probability", prior=0.5)
    features["probability.evidence.success_distribution"] = _collection_feature("probability.evidence.success_distribution", evidence.get("success_distribution"), source="probability")
    features["probability.evidence.failure_distribution"] = _collection_feature("probability.evidence.failure_distribution", evidence.get("failure_distribution"), source="probability")
    features["probability.evidence.major_failure_modes"] = _collection_feature("probability.evidence.major_failure_modes", evidence.get("major_failure_modes"), source="probability")

    add("risk.execution_quality", risk.get("execution_quality"), source="risk", prior=0.5)
    add("risk.risk_adjustment", risk.get("risk_adjustment"), source="risk", prior=0.5)
    add("risk.drawdown_probability", risk.get("drawdown_probability"), source="risk", prior=0.5)
    add("risk.expected_max_drawdown", risk.get("expected_max_drawdown"), source="risk", prior=0.03)
    features["risk.risk_flags"] = _collection_feature("risk.risk_flags", risk.get("risk_flags"), source="risk")
    add("risk.diagnostics.reward_risk", risk_diag.get("reward_risk"), source="risk", prior=1.0)
    features["risk.diagnostics.execution_state"] = _enum_feature(
        "risk.diagnostics.execution_state",
        risk_diag.get("execution_state"),
        source="risk",
        mapping={"actionable": 0.75, "observe_only": 0.45, "unavailable": 0.35},
    )
    for key in ("entry", "stop", "take_profit"):
        value = risk.get(key)
        features[f"risk.{key}"] = {
            "name": f"risk.{key}",
            "value": 1.0 if _has_price(value) else 0.5,
            "available": _has_price(value),
            "quality": 1.0 if _has_price(value) else 0.0,
            "missing": not _has_price(value),
            "source": "risk",
            "raw": value if value is not None else {},
        }

    add("ranking.ranking_score", ranking.get("ranking_score"), source="ranking", prior=0.0)
    add("ranking.ranking_factors.expected_return_3d", ranking_factors.get("expected_return_3d"), source="ranking", prior=0.0)
    add("ranking.ranking_factors.win_probability_3d", ranking_factors.get("win_probability_3d"), source="ranking", prior=0.5)
    add("ranking.ranking_factors.execution_quality", ranking_factors.get("execution_quality"), source="ranking", prior=0.5)
    add("ranking.ranking_factors.confidence", ranking_factors.get("confidence"), source="ranking", prior=0.5)
    add("ranking.ranking_factors.risk_adjustment", ranking_factors.get("risk_adjustment"), source="ranking", prior=0.5)

    features["signal.signal_type"] = _enum_feature(
        "signal.signal_type",
        signal.get("signal_type") or candidate.get("signal_type"),
        source="signal",
        mapping={"breakout_pressure": 0.68, "breakout_pullback": 0.64, "trend_pullback": 0.60, "trend_continuation": 0.58, "structure_watch": 0.50},
    )
    for key, prior in {
        "close": 0.0,
        "atr_pct": 0.03,
        "support": 0.0,
        "pullback_quality": 0.5,
        "volume_ratio": 1.0,
        "liquidity_score": 0.5,
    }.items():
        add(f"signal.features.{key}", signal_features.get(key), source="signal", prior=prior)
    for key, value in sorted(signal_vector.items()):
        parsed = _float_or_none(value)
        if parsed is not None:
            add(f"signal.feature_vector.{key}", parsed, source="signal", prior=0.5)

    features["market.grade"] = _enum_feature("market.grade", market_context.get("grade") or market_context.get("market_regime"), source="market_context", mapping={"A": 0.65, "B": 0.58, "C": 0.50, "D": 0.42, "a": 0.65, "b": 0.58, "c": 0.50, "d": 0.42})
    features["market.market_regime"] = _enum_feature("market.market_regime", market_context.get("market_regime"), source="market_context", mapping={"A": 0.65, "B": 0.58, "C": 0.50, "D": 0.42, "a": 0.65, "b": 0.58, "c": 0.50, "d": 0.42})
    features["market.regime_reasons"] = _collection_feature("market.regime_reasons", market_context.get("regime_reasons"), source="market_context")
    raw_market = dict(market_context.get("raw") or {})
    for key, value in sorted(raw_market.items()):
        parsed = _float_or_none(value)
        if parsed is not None:
            add(f"market.raw.{key}", parsed, source="market_context", prior=0.5)

    total = len(features)
    available = sum(1 for value in features.values() if bool(value.get("available")))
    missing = [key for key, value in features.items() if bool(value.get("missing"))]
    flags: List[str] = []
    if missing:
        flags.append("missing_features_present")
    if available / max(1, total) < 0.65:
        flags.append("feature_coverage_low")
    if _safe_float(evidence.get("effective_sample_size"), 0.0) < 10.0:
        flags.append("effective_sample_low")
    if _safe_float(probability.get("uncertainty"), 0.0) >= 0.30:
        flags.append("uncertainty_high")
    return {
        "features": features,
        "feature_coverage": float(available / max(1, total)),
        "missing_features": missing,
        "available_count": available,
        "total_count": total,
        "data_quality_flags": flags,
    }


def _feature_value(bundle: dict, key: str, default: float = 0.0) -> float:
    item = (bundle.get("features") or {}).get(key) or {}
    return _safe_float(item.get("value"), default)


def _prob_bucket(probability: float) -> str:
    p = _clamp(probability, 0.0, 1.0, 0.5)
    lo = math.floor(p * 10.0) / 10.0
    hi = min(1.0, lo + 0.1)
    if p >= 1.0:
        lo, hi = 0.9, 1.0
    return f"p_{lo:.1f}_{hi:.1f}"


def _sample_bucket(effective_n: float) -> str:
    if effective_n < 10.0:
        return "n_low"
    if effective_n < 40.0:
        return "n_mid"
    return "n_high"


def _signal_type(candidate: dict) -> str:
    signal = dict(candidate.get("signal") or {})
    return str(signal.get("signal_type") or candidate.get("signal_type") or "unknown")


def _calibration_key(candidate: dict, market_context: dict, raw_probability: float, effective_n: float) -> str:
    grade = str(market_context.get("grade") or market_context.get("market_regime") or "unknown").upper()
    return "|".join([_prob_bucket(raw_probability), _sample_bucket(effective_n), grade, _signal_type(candidate)])


def _calibrated_probability(candidate: dict, market_context: dict, state: dict, raw_probability: float, effective_n: float) -> Tuple[float, Dict[str, Any]]:
    key = _calibration_key(candidate, market_context, raw_probability, effective_n)
    bucket = dict((state.get("calibration") or {}).get(key) or {})
    count = int(_safe_float(bucket.get("count"), 0))
    if count <= 0:
        value = 0.65 * _clamp(raw_probability, 0.0, 1.0, 0.5) + 0.35 * 0.5
        return float(_clamp(value, 0.0, 1.0, 0.5)), {"bucket_key": key, "source": "raw_probability_shrinkage", "count": 0}
    alpha = _safe_float(bucket.get("alpha"), 2.0)
    beta = _safe_float(bucket.get("beta"), 2.0)
    wins = _safe_float(bucket.get("wins"), 0.0)
    value = (alpha + wins) / max(1e-9, alpha + beta + count)
    return float(_clamp(value, 0.0, 1.0, 0.5)), {"bucket_key": key, "source": "beta_binomial", **bucket}


def _normalize_ranking_score(value: float) -> float:
    if value <= 0.0:
        return 0.0
    return _clamp(value / (abs(value) + 0.004), 0.0, 1.0, 0.0)


def _strength(adaptive_score: float, confidence: float, coverage: float, risk_penalty: float, uncertainty: float, effective_n: float) -> str:
    if adaptive_score >= 0.64 and confidence >= 0.58 and coverage >= 0.75 and risk_penalty <= 0.35:
        return "strong"
    if adaptive_score >= 0.54 and confidence >= 0.42 and uncertainty <= 0.32:
        return "normal"
    if effective_n < 10.0 or coverage < 0.65:
        return "exploratory"
    return "cautious"


def _action(strength: str, setup_score: float, adaptive_score: float) -> str:
    if strength in {"strong", "normal"} and setup_score >= 0.50 and adaptive_score >= 0.50:
        return "ENTRY"
    if strength in {"cautious", "exploratory"}:
        return "WATCH"
    return "WAIT"


def score_candidate(candidate: dict, market_context: dict, state: dict | None = None) -> dict:
    state = _normalize_state(state or load_policy_state())
    market_context = dict(market_context or {})
    candidate = dict(candidate or {})
    symbol = _normalize_symbol(candidate.get("symbol") or candidate.get("code"))
    feature_bundle = build_missing_aware_features(candidate, market_context)
    probability = dict(candidate.get("probability") or {})
    risk = dict(candidate.get("risk") or {})
    evidence = dict(probability.get("evidence") or {})
    risk_flags = [str(item) for item in (risk.get("risk_flags") or candidate.get("risk_flags") or [])]

    raw_probability = _clamp(probability.get("up_probability_3d"), 0.0, 1.0, 0.5)
    effective_n = _safe_float(evidence.get("effective_sample_size"), 0.0)
    sample_size = _safe_float(evidence.get("sample_size"), 0.0)
    mean_similarity = _clamp(evidence.get("mean_similarity"), 0.0, 1.0, 0.5)
    calibrated_probability, calibration_debug = _calibrated_probability(candidate, market_context, state, raw_probability, effective_n)
    expected_edge = _safe_float(probability.get("expected_return_3d"), 0.0)
    predicted_drawdown = _clamp(risk.get("drawdown_probability") or probability.get("drawdown_probability"), 0.0, 1.0, 0.5)
    expected_max_drawdown = abs(_safe_float(risk.get("expected_max_drawdown") or probability.get("expected_max_drawdown"), 0.03))
    uncertainty = _clamp(probability.get("uncertainty"), 0.0, 1.0, 0.35)
    feature_coverage = float(feature_bundle.get("feature_coverage") or 0.0)

    signal_score = _clamp(
        0.25 * _feature_value(feature_bundle, "signal.signal_type", 0.5)
        + 0.22 * _feature_value(feature_bundle, "signal.features.pullback_quality", 0.5)
        + 0.18 * min(1.0, _feature_value(feature_bundle, "signal.features.volume_ratio", 1.0) / 2.5)
        + 0.18 * _feature_value(feature_bundle, "signal.features.liquidity_score", 0.5)
        + 0.17 * _feature_value(feature_bundle, "signal.feature_vector.trend_strength", 0.5),
        0.0,
        1.0,
        0.5,
    )
    memory_sample = _clamp(effective_n / 40.0, 0.0, 1.0, 0.0)
    memory_count = _clamp(sample_size / 80.0, 0.0, 1.0, 0.0)
    memory_score = _clamp(0.45 + 0.28 * memory_sample + 0.17 * memory_count + 0.10 * (mean_similarity - 0.5), 0.30, 0.85, 0.5)
    probability_score = _clamp(0.72 * calibrated_probability + 0.28 * _clamp(0.5 + expected_edge * 6.0, 0.0, 1.0, 0.5), 0.0, 1.0, 0.5)
    risk_penalty = _clamp(0.50 * predicted_drawdown + 0.25 * min(1.0, expected_max_drawdown / 0.10) + 0.25 * min(1.0, len(risk_flags) / 4.0), 0.0, 1.0, 0.0)
    setup_score = _clamp(
        0.45 * _feature_value(feature_bundle, "risk.execution_quality", 0.5)
        + 0.25 * min(1.0, _feature_value(feature_bundle, "risk.diagnostics.reward_risk", 1.0) / 2.5)
        + 0.10 * _feature_value(feature_bundle, "risk.entry", 0.5)
        + 0.10 * _feature_value(feature_bundle, "risk.stop", 0.5)
        + 0.10 * _feature_value(feature_bundle, "risk.take_profit", 0.5),
        0.0,
        1.0,
        0.5,
    )
    ranking_score_norm = _normalize_ranking_score(_safe_float((candidate.get("ranking") or {}).get("ranking_score") or candidate.get("ranking_score"), 0.0))
    regime_score = _feature_value(feature_bundle, "market.grade", 0.5)
    exploration_score = _clamp(0.35 * (1.0 - memory_sample) + 0.30 * (1.0 - feature_coverage) + 0.35 * uncertainty, 0.0, 1.0, 0.0)

    weights = _project_weights(dict(state.get("expert_weights") or DEFAULT_WEIGHTS))
    expert_scores = {
        "signal": signal_score,
        "memory": memory_score,
        "probability": probability_score,
        "risk": risk_penalty,
        "setup": setup_score,
        "ranking": ranking_score_norm,
        "regime": regime_score,
        "exploration": exploration_score,
    }
    expert_contributions = {
        "signal": weights["signal"] * signal_score,
        "memory": weights["memory"] * memory_score,
        "probability": weights["probability"] * probability_score,
        "risk": -weights["risk"] * risk_penalty,
        "setup": weights["setup"] * setup_score,
        "ranking": weights["ranking"] * ranking_score_norm,
        "regime": weights["regime"] * regime_score,
        "exploration": weights["exploration"] * exploration_score,
    }
    adaptive_score = _clamp(sum(expert_contributions.values()), 0.0, 1.0, 0.0)
    confidence_base = _clamp(probability.get("confidence"), 0.0, 1.0, 0.5)
    confidence = _clamp(0.46 * confidence_base + 0.24 * feature_coverage + 0.16 * memory_sample + 0.14 * (1.0 - uncertainty), 0.0, 1.0, 0.4)
    if exploration_score > 0.45:
        confidence = _clamp(confidence - 0.12 * exploration_score, 0.0, 1.0, confidence)
    recommendation_strength = _strength(adaptive_score, confidence, feature_coverage, risk_penalty, uncertainty, effective_n)
    action = _action(recommendation_strength, setup_score, adaptive_score)

    reason_codes = ["adaptive_policy"]
    if effective_n < 10.0:
        reason_codes.append("low_effective_sample_exploratory")
    if feature_coverage < 0.75:
        reason_codes.append("missing_aware_score")
    if uncertainty >= 0.30:
        reason_codes.append("uncertainty_reduces_confidence")
    if risk_flags:
        reason_codes.append("risk_flags_penalized_not_gated")
    if calibrated_probability != raw_probability:
        reason_codes.append("beta_calibrated_probability")

    return {
        "symbol": symbol,
        "adaptive_score": float(adaptive_score),
        "expected_edge": float(expected_edge),
        "calibrated_probability": float(calibrated_probability),
        "predicted_drawdown": float(predicted_drawdown),
        "confidence": float(confidence),
        "uncertainty": float(uncertainty),
        "feature_coverage": float(feature_coverage),
        "recommendation_strength": recommendation_strength,
        "action": action,
        "expert_scores": {key: float(value) for key, value in expert_scores.items()},
        "expert_contributions": {key: float(value) for key, value in expert_contributions.items()},
        "missing_features": list(feature_bundle.get("missing_features") or []),
        "reason_codes": reason_codes,
        "calibration": calibration_debug,
        "feature_summary": {
            "available_count": feature_bundle.get("available_count"),
            "total_count": feature_bundle.get("total_count"),
            "data_quality_flags": list(feature_bundle.get("data_quality_flags") or []),
        },
    }


def _hard_block(candidate: dict, market_context: dict) -> str | None:
    if bool((market_context or {}).get("hard_block")):
        reasons = list((market_context or {}).get("hard_block_reasons") or [])
        return str(reasons[0]) if reasons else "market_context_hard_block"
    if bool((candidate or {}).get("hard_block")):
        reasons = list((candidate or {}).get("hard_block_reasons") or [])
        return str(reasons[0]) if reasons else "candidate_hard_block"
    risk = dict((candidate or {}).get("risk") or {})
    if bool(risk.get("hard_block")):
        reasons = list(risk.get("hard_block_reasons") or [])
        return str(reasons[0]) if reasons else "risk_hard_block"
    return None


def select_candidates(
    ranked_candidates: list[dict],
    *,
    topk: int,
    market_context: dict,
    risk_profile: str = "normal",
    state: dict | None = None,
) -> dict:
    state = _normalize_state(state or load_policy_state())
    ranked = list(ranked_candidates or [])
    if not ranked:
        return {
            "final_decision": "no_trade",
            "selected_symbols": [],
            "adaptive_candidates": [],
            "policy_state_version": state.get("version", 1),
            "policy_debug": {
                "scored_count": 0,
                "invalid_count": 0,
                "selection_policy": "adaptive_score_topk_no_low_sample_gate",
                "reason": "no_ranked_candidates",
                "risk_profile": risk_profile,
            },
            "validator_result": {
                "ok": True,
                "policy": "adaptive_policy_single_path",
                "selected_from_ranked_candidates": True,
                "reason": "no_ranked_candidates",
            },
        }

    scored: List[Dict[str, Any]] = []
    invalid: List[Dict[str, Any]] = []
    for idx, candidate in enumerate(ranked):
        symbol = _normalize_symbol((candidate or {}).get("symbol") or (candidate or {}).get("code"))
        if not symbol:
            invalid.append({"index": idx, "reason": "symbol_missing"})
            continue
        block = _hard_block(candidate, market_context)
        if block:
            invalid.append({"index": idx, "symbol": symbol, "reason": block})
            continue
        try:
            scored_item = score_candidate(candidate, market_context, state)
            if not math.isfinite(_safe_float(scored_item.get("adaptive_score"), float("nan"))):
                raise ValueError("adaptive_score_non_finite")
            scored.append(scored_item)
        except Exception as ex:  # noqa: BLE001
            invalid.append({"index": idx, "symbol": symbol, "reason": f"score_error:{type(ex).__name__}"})

    scored.sort(key=lambda item: float(item.get("adaptive_score") or 0.0), reverse=True)
    selected = scored[: max(0, int(topk))]
    if not selected:
        reason = "all_candidates_invalid_or_hard_blocked"
        return {
            "final_decision": "no_trade",
            "selected_symbols": [],
            "adaptive_candidates": scored,
            "policy_state_version": state.get("version", 1),
            "policy_debug": {
                "scored_count": len(scored),
                "invalid_count": len(invalid),
                "invalid_candidates": invalid[:20],
                "selection_policy": "adaptive_score_topk_no_low_sample_gate",
                "reason": reason,
                "risk_profile": risk_profile,
            },
            "validator_result": {
                "ok": True,
                "policy": "adaptive_policy_single_path",
                "selected_from_ranked_candidates": True,
                "reason": reason,
            },
        }
    return {
        "final_decision": "recommend",
        "selected_symbols": [str(item.get("symbol")) for item in selected],
        "adaptive_candidates": scored,
        "policy_state_version": state.get("version", 1),
        "policy_debug": {
            "scored_count": len(scored),
            "invalid_count": len(invalid),
            "invalid_candidates": invalid[:20],
            "selection_policy": "adaptive_score_topk_no_low_sample_gate",
            "risk_profile": risk_profile,
        },
        "validator_result": {
            "ok": True,
            "policy": "adaptive_policy_single_path",
            "selected_from_ranked_candidates": True,
        },
    }


def _record_pick(record: dict) -> dict:
    pick = record.get("pick")
    return dict(pick) if isinstance(pick, dict) else {}


def _record_outcome(record: dict) -> dict:
    outcome = record.get("outcome")
    return dict(outcome) if isinstance(outcome, dict) else {}


def _reward(outcome: dict) -> float:
    reward = (
        1.5 * _safe_float(outcome.get("return_3d"), 0.0)
        + 0.7 * _safe_float(outcome.get("max_profit"), 0.0)
        + 1.0 * _safe_float(outcome.get("max_drawdown"), 0.0)
        + (0.03 if bool(outcome.get("success") is True) else -0.03)
    )
    return _clamp(reward, -0.08, 0.08, 0.0)


def _calibration_update_key(pick: dict) -> str:
    probability = dict(pick.get("probability") or {})
    adaptive = dict(pick.get("adaptive_policy") or {})
    evidence = dict(probability.get("evidence") or {})
    signal = dict(pick.get("signal") or {})
    market_context = dict(pick.get("market_context") or signal.get("market_context") or {})
    raw = _safe_float(probability.get("up_probability_3d") or adaptive.get("calibrated_probability"), 0.5)
    return _calibration_key(pick, market_context, raw, _safe_float(evidence.get("effective_sample_size"), 0.0))


def update_policy_state_from_outcomes(state: dict, records: list[dict]) -> dict:
    state = _normalize_state(state)
    calibration = dict(state.get("calibration") or {})
    weights = _project_weights(dict(state.get("expert_weights") or DEFAULT_WEIGHTS))
    recommended_updates = 0
    calibration_updates = 0
    eta = 0.05

    for record in list(records or []):
        pick = _record_pick(record)
        outcome = _record_outcome(record)
        if not pick or not outcome or outcome.get("complete") is not True:
            continue
        key = _calibration_update_key(pick)
        bucket = dict(calibration.get(key) or {"alpha": 2.0, "beta": 2.0, "wins": 0, "count": 0})
        bucket["alpha"] = _safe_float(bucket.get("alpha"), 2.0)
        bucket["beta"] = _safe_float(bucket.get("beta"), 2.0)
        bucket["wins"] = int(_safe_float(bucket.get("wins"), 0)) + (1 if bool(outcome.get("success") is True) else 0)
        bucket["count"] = int(_safe_float(bucket.get("count"), 0)) + 1
        calibration[key] = bucket
        calibration_updates += 1

        if str(record.get("role") or "").lower() != "recommended":
            continue
        clipped_reward = _reward(outcome)
        recommended_updates += 1
        adaptive = dict(pick.get("adaptive_policy") or {})
        contributions = dict(adaptive.get("expert_contributions") or pick.get("expert_contributions") or {})
        if not contributions:
            continue
        for expert in EXPERT_KEYS:
            contribution = abs(_safe_float(contributions.get(expert), 0.0))
            if contribution <= 0.0:
                continue
            weights[expert] = weights[expert] * math.exp(eta * contribution * clipped_reward)
        weights = _project_weights(weights)

    state["calibration"] = calibration
    state["expert_weights"] = _project_weights(weights)
    state["update_count"] = int(state.get("update_count") or 0) + recommended_updates
    state["updated_at"] = now_iso()
    state["last_update_meta"] = {
        "records_seen": len(records or []),
        "recommended_updates": recommended_updates,
        "calibration_updates": calibration_updates,
        "updated_at": state["updated_at"],
    }
    return state
