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
    NATIVE_SERENITY_FORMULA_VERSION,
    SerenityCounterfactualArm,
    SerenityPolicyState,
    SerenityReferenceSnapshot,
)


FORMULA_VERSION = NATIVE_SERENITY_FORMULA_VERSION
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
    if "alpha_value" in item:
        return max(-1.0, min(1.0, _safe_float(item.get("alpha_value"), 0.0)))
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


def _causal_signal_payload(signal: FrozenSerenitySignal) -> Dict[str, Any]:
    payload = signal.model_dump(mode="json")
    # generated_at is observability metadata, not a causal scoring input. An
    # equivalent rebuild must retain the same immutable reference identity.
    payload.pop("generated_at", None)
    return payload


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
    actual_weight: float = 0.0,
    policy_state: str = "shadow",
    baseline_selected_symbols: Sequence[str] = (),
    applied_selected_symbols: Sequence[str] = (),
    would_change_topk: bool = False,
) -> str:
    return _checksum(
        {
            "decision_context_snapshot_id": decision_context_snapshot_id,
            "decision_day": decision_day,
            "decision_at": decision_at,
            "signals": {symbol: _causal_signal_payload(signal) for symbol, signal in sorted(signals.items())},
            "arms": [arm.model_dump(mode="json") for arm in arms],
            "reference_arms": [arm.model_dump(mode="json") for arm in reference_arms],
            "risk_plans": {
                symbol: dict(plan)
                for symbol, plan in sorted((risk_plans or {}).items())
            },
            "learning_sample_id": str(learning_sample_id or ""),
            "actual_weight": round(float(actual_weight), 2),
            "policy_state": str(policy_state),
            "baseline_selected_symbols": list(baseline_selected_symbols),
            "applied_selected_symbols": list(applied_selected_symbols),
            "would_change_topk": bool(would_change_topk),
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
            candidate.get("baseline_adaptive_score", candidate.get("adaptive_score")),
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
        resolved_mode != "native"
        or state.state not in {"probation", "active"}
        or not state.bootstrap_run_id
    ):
        return 0.0
    weight = _safe_float(state.applied_weight, -1.0)
    max_weight = _safe_float(state.max_weight, 0.0)
    if weight < 0.0 or weight > 0.08 or max_weight < 0.0 or max_weight > 0.08:
        return 0.0
    return max(0.0, min(max_weight, 0.08, round(weight, 2)))


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
        actual_weight=float(policy.get("applied_weight") or 0.0),
        policy_state=str(policy.get("state") or "shadow"),
        baseline_selected_symbols=list(policy.get("baseline_selected_symbols") or []),
        applied_selected_symbols=list(policy.get("applied_selected_symbols") or []),
        would_change_topk=bool(policy.get("would_change_topk")),
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
