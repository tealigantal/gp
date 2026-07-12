from __future__ import annotations

import json
import math
from copy import deepcopy
from hashlib import sha256
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ..core.config import load_config
from ..runtime.utils import now_iso
from ..serenity.models import (
    FrozenSerenitySignal,
    SerenityCounterfactualArm,
    SerenityPolicyState,
    SerenityReferenceSnapshot,
)


FORMULA_VERSION = "SerenityAddon.v1"
WEIGHT_ARMS = tuple(round(step / 100.0, 2) for step in range(0, 9))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if not math.isfinite(out):
        return default
    return out


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    parsed = _safe_float(value, lo)
    return lo if parsed < lo else hi if parsed > hi else parsed


def signal_value(
    signal: FrozenSerenitySignal | Mapping[str, Any] | None,
    *,
    allow_reference_only: bool = False,
) -> float:
    if signal is None:
        return 0.0
    item = signal.model_dump() if isinstance(signal, FrozenSerenitySignal) else dict(signal)
    if str(item.get("status") or "") != "available" or int(item.get("availability") or 0) != 1:
        return 0.0
    if not allow_reference_only and not bool(item.get("learning_eligible")):
        return 0.0
    direction = -1.0 if _safe_float(item.get("direction"), 0.0) < 0 else 1.0 if _safe_float(item.get("direction"), 0.0) > 0 else 0.0
    return direction * _clamp(item.get("confidence")) * _clamp(item.get("source_quality"))


def decision_score(
    baseline_score: Any,
    signal: FrozenSerenitySignal | Mapping[str, Any] | None,
    weight: float,
    *,
    allow_reference_only: bool = False,
) -> tuple[float, float]:
    baseline = _clamp(baseline_score)
    bounded_weight = max(0.0, min(0.08, round(_safe_float(weight), 2)))
    score = _clamp(
        baseline + bounded_weight * signal_value(signal, allow_reference_only=allow_reference_only)
    )
    return score, score - baseline


def _checksum(payload: Any) -> str:
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def counterfactual_arm_checksum(arm: SerenityCounterfactualArm | Mapping[str, Any]) -> str:
    item = arm.model_dump(mode="json") if isinstance(arm, SerenityCounterfactualArm) else dict(arm)
    return _checksum(
        {
            "weight": round(float(item.get("weight") or 0.0), 2),
            "ranked_symbols": list(item.get("ranked_symbols") or []),
            "scores": dict(item.get("scores") or {}),
        }
    )


def reference_input_checksum(
    *,
    decision_context_snapshot_id: str | None,
    decision_day: str,
    decision_at: str,
    signals: Mapping[str, FrozenSerenitySignal],
    arms: Sequence[SerenityCounterfactualArm],
    reference_arms: Sequence[SerenityCounterfactualArm] = (),
    risk_plans: Mapping[str, Mapping[str, Any]] | None = None,
    learning_sample_id: str = "",
) -> str:
    return _checksum(
        {
            "decision_context_snapshot_id": decision_context_snapshot_id,
            "decision_day": decision_day,
            "decision_at": decision_at,
            "signals": {symbol: signal.model_dump(mode="json") for symbol, signal in sorted(signals.items())},
            "arms": [arm.model_dump(mode="json") for arm in arms],
            "reference_arms": [arm.model_dump(mode="json") for arm in reference_arms],
            "risk_plans": {
                symbol: dict(plan)
                for symbol, plan in sorted((risk_plans or {}).items())
            },
            "learning_sample_id": str(learning_sample_id or ""),
            "formula_version": FORMULA_VERSION,
        }
    )


def freeze_risk_plan(value: Mapping[str, Any] | None) -> Dict[str, Any]:
    item = dict(value or {})
    return {
        "entry": deepcopy(dict(item.get("entry") or {})),
        "stop": deepcopy(dict(item.get("stop") or {})),
        "take_profit": deepcopy(dict(item.get("take_profit") or {})),
    }


def reference_learning_sample_id(
    *,
    decision_day: str,
    signals: Mapping[str, FrozenSerenitySignal],
    arms: Sequence[SerenityCounterfactualArm],
    risk_plans: Mapping[str, Mapping[str, Any]],
) -> str:
    return "sersample_" + _checksum(
        {
            "decision_day": str(decision_day),
            "signals": {
                symbol: {
                    "fact_ids": list(signal.fact_ids),
                    "status": signal.status,
                    "availability": signal.availability,
                    "direction": signal.direction,
                    "confidence": signal.confidence,
                    "source_quality": signal.source_quality,
                    "learning_eligible": signal.learning_eligible,
                }
                for symbol, signal in sorted(signals.items())
            },
            "arms": [
                {
                    "weight": arm.weight,
                    "selected_symbols": list(arm.selected_symbols),
                    "scores": dict(arm.scores),
                }
                for arm in arms
            ],
            "risk_plans": {
                symbol: dict(plan) for symbol, plan in sorted(risk_plans.items())
            },
            "formula_version": FORMULA_VERSION,
        }
    )[:24]


def _ranked_for_weight(
    candidates: Sequence[Dict[str, Any]],
    signals: Mapping[str, FrozenSerenitySignal],
    *,
    weight: float,
    topk: int,
    allow_reference_only: bool = False,
) -> SerenityCounterfactualArm:
    rows: List[Dict[str, Any]] = []
    for original_rank, candidate in enumerate(candidates):
        symbol = str(candidate.get("symbol") or "")
        score, adjustment = decision_score(
            candidate.get("adaptive_score"),
            signals.get(symbol),
            weight,
            allow_reference_only=allow_reference_only,
        )
        rows.append(
            {
                "symbol": symbol,
                "score": score,
                "adjustment": adjustment,
                "original_rank": original_rank,
            }
        )
    rows.sort(key=lambda row: (-float(row["score"]), int(row["original_rank"]), str(row["symbol"])))
    ranked_symbols = [str(row["symbol"]) for row in rows]
    selected_symbols = ranked_symbols[: max(0, int(topk))]
    scores = {str(row["symbol"]): float(row["score"]) for row in rows}
    arm_payload = {"weight": round(weight, 2), "ranked_symbols": ranked_symbols, "scores": scores}
    return SerenityCounterfactualArm(
        weight=round(weight, 2),
        ranked_symbols=ranked_symbols,
        selected_symbols=selected_symbols,
        scores=scores,
        checksum=_checksum(arm_payload),
    )


def build_serenity_counterfactuals(
    adaptive_candidates: Sequence[Dict[str, Any]],
    signals: Mapping[str, FrozenSerenitySignal],
    *,
    topk: int,
    weights: Iterable[float] = WEIGHT_ARMS,
    allow_reference_only: bool = False,
) -> List[SerenityCounterfactualArm]:
    return [
        _ranked_for_weight(
            adaptive_candidates,
            signals,
            weight=max(0.0, min(0.08, round(float(weight), 2))),
            topk=topk,
            allow_reference_only=allow_reference_only,
        )
        for weight in weights
    ]


def effective_weight(state: SerenityPolicyState, *, mode: str | None = None) -> float:
    resolved_mode = str(mode or load_config().serenity.mode)
    if (
        resolved_mode != "auto"
        or state.state not in {"probation", "active"}
        or not state.bootstrap_run_id
    ):
        return 0.0
    weight = _safe_float(state.applied_weight, -1.0)
    max_weight = _safe_float(state.max_weight, 0.0)
    if weight < 0.0 or weight > 0.08 or max_weight < 0.0 or max_weight > 0.08:
        return 0.0
    return max(0.0, min(max_weight, 0.08, round(weight, 2)))


def apply_serenity_addon(
    adaptive_output: Dict[str, Any],
    signals: Mapping[str, FrozenSerenitySignal],
    state: SerenityPolicyState,
    *,
    topk: int,
    mode: str | None = None,
) -> Dict[str, Any]:
    base = deepcopy(dict(adaptive_output or {}))
    base_candidates = [dict(item) for item in list(base.get("adaptive_candidates") or [])]
    if not base_candidates:
        base["serenity_policy"] = {
            "formula_version": FORMULA_VERSION,
            "state": state.state,
            "epoch": state.epoch,
            "applied_weight": 0.0,
            "max_weight": state.max_weight,
        }
        base["serenity_counterfactuals"] = []
        return base
    arms = build_serenity_counterfactuals(base_candidates, signals, topk=topk)
    reference_arms = build_serenity_counterfactuals(
        base_candidates,
        signals,
        topk=topk,
        allow_reference_only=True,
    )
    applied_weight = effective_weight(state, mode=mode)
    applied_arm = next((arm for arm in arms if abs(arm.weight - applied_weight) < 1e-9), arms[0])
    baseline_arm = arms[0]
    reference_max_arm = reference_arms[-1]
    original_rank = {str(item.get("symbol") or ""): idx for idx, item in enumerate(base_candidates)}
    by_symbol = {str(item.get("symbol") or ""): dict(item) for item in base_candidates}
    ranked_candidates: List[Dict[str, Any]] = []
    for symbol in applied_arm.ranked_symbols:
        candidate = by_symbol[symbol]
        baseline_score = _clamp(candidate.get("adaptive_score"))
        score = float(applied_arm.scores[symbol])
        signal = signals.get(symbol)
        adjustment = float(score - baseline_score)
        binding_candidate = bool(
            applied_weight > 0.0
            and signal is not None
            and signal.learning_eligible
            and abs(adjustment) > 1e-12
        )
        candidate.update(
            {
                "decision_score": score,
                "serenity_adjustment": adjustment,
                "serenity_status": signal.status if signal else "not_ready",
                "serenity_fact_ids": list(signal.fact_ids if signal else []),
                "serenity_learning_eligible": bool(signal.learning_eligible) if signal else False,
                "serenity_input_hash": signal.input_hash if signal else None,
                "serenity_policy_state": state.state,
                "serenity_weight": applied_weight,
                "serenity_non_binding": not binding_candidate,
                "serenity_would_change_topk": applied_arm.selected_symbols
                != baseline_arm.selected_symbols,
                "serenity_reference_would_change_topk": reference_max_arm.selected_symbols
                != baseline_arm.selected_symbols,
            }
        )
        ranked_candidates.append(candidate)
    ranked_candidates.sort(
        key=lambda item: (
            -float(item.get("decision_score") or 0.0),
            original_rank.get(str(item.get("symbol") or ""), 10**9),
            str(item.get("symbol") or ""),
        )
    )
    base["adaptive_candidates"] = ranked_candidates
    base["selected_symbols"] = list(applied_arm.selected_symbols)
    base["final_decision"] = "recommend" if applied_arm.selected_symbols else "no_trade"
    base["serenity_policy"] = {
        "formula_version": FORMULA_VERSION,
        "state": state.state,
        "epoch": state.epoch,
        "applied_weight": applied_weight,
        "max_weight": state.max_weight,
        "would_change_topk": applied_arm.selected_symbols != baseline_arm.selected_symbols,
        "baseline_selected_symbols": baseline_arm.selected_symbols,
        "applied_selected_symbols": applied_arm.selected_symbols,
        "reference_would_change_topk": reference_max_arm.selected_symbols != baseline_arm.selected_symbols,
        "reference_selected_symbols_at_max_weight": reference_max_arm.selected_symbols,
    }
    base["serenity_counterfactuals"] = [arm.model_dump(mode="json") for arm in arms]
    base["serenity_reference_counterfactuals"] = [arm.model_dump(mode="json") for arm in reference_arms]
    validator = dict(base.get("validator_result") or {})
    validator.update(
        {
            "serenity_weight_bounded": 0.0 <= applied_weight <= 0.08,
            "serenity_hard_blocks_unchanged": True,
            "serenity_baseline_preserved": True,
        }
    )
    base["validator_result"] = validator
    return base


def build_reference_snapshot(
    *,
    decision_context_snapshot_id: str | None,
    decision_day: str,
    decision_at: str,
    adaptive_output: Dict[str, Any],
    signals: Mapping[str, FrozenSerenitySignal],
    risk_plans: Mapping[str, Mapping[str, Any]] | None = None,
) -> SerenityReferenceSnapshot:
    policy = dict(adaptive_output.get("serenity_policy") or {})
    arms = [SerenityCounterfactualArm.model_validate(item) for item in list(adaptive_output.get("serenity_counterfactuals") or [])]
    reference_arms = [
        SerenityCounterfactualArm.model_validate(item)
        for item in list(adaptive_output.get("serenity_reference_counterfactuals") or [])
    ]
    outcome_symbols = sorted(
        {
            symbol
            for arm in arms
            for symbol in arm.selected_symbols
            if str(symbol)
        }
    )
    frozen_risk_plans = {
        symbol: freeze_risk_plan((risk_plans or {}).get(symbol))
        for symbol in outcome_symbols
    }
    learning_sample_id = reference_learning_sample_id(
        decision_day=decision_day,
        signals=signals,
        arms=arms,
        risk_plans=frozen_risk_plans,
    )
    input_checksum = reference_input_checksum(
        decision_context_snapshot_id=decision_context_snapshot_id,
        decision_day=decision_day,
        decision_at=decision_at,
        signals=signals,
        arms=arms,
        reference_arms=reference_arms,
        risk_plans=frozen_risk_plans,
        learning_sample_id=learning_sample_id,
    )
    snapshot_id = "sersnap_" + input_checksum[:24]
    return SerenityReferenceSnapshot(
        snapshot_id=snapshot_id,
        decision_context_snapshot_id=decision_context_snapshot_id,
        decision_day=decision_day,
        decision_at=decision_at,
        actual_weight=float(policy.get("applied_weight") or 0.0),
        policy_state=str(policy.get("state") or "shadow"),
        target_symbols=list(signals),
        signals=dict(signals),
        risk_plans=frozen_risk_plans,
        counterfactual_arms=arms,
        reference_counterfactual_arms=reference_arms,
        baseline_selected_symbols=list(policy.get("baseline_selected_symbols") or []),
        applied_selected_symbols=list(policy.get("applied_selected_symbols") or []),
        would_change_topk=bool(policy.get("would_change_topk")),
        input_checksum=input_checksum,
        learning_sample_id=learning_sample_id,
        created_at=now_iso(),
    )
