from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from ..contracts.objects import AdvicePick, MarketBook
from ..core.config import load_config
from ..serenity.models import (
    FrozenSerenitySignal,
    NATIVE_SERENITY_FORMULA_VERSION,
    SerenityFact,
)
from ..serenity.store import (
    candidate_target_identity_hash,
    serenity_batch_semantic_revision,
)
from .producer import SELECTION_POLICY
from .producer import producer_is_compatible


_TOLERANCE = 1e-9
_BASE_EXPERT_KEYS = (
    "signal",
    "memory",
    "probability",
    "risk",
    "setup",
    "ranking",
    "regime",
    "exploration",
)
_EXPERT_KEYS = {
    *_BASE_EXPERT_KEYS,
    "serenity",
}


def serenity_runtime_binding_check(
    source_meta: dict[str, Any], current: dict[str, Any]
) -> tuple[str | None, dict[str, Any]]:
    snapshot_target_id = str(source_meta.get("serenity_target_id") or "")
    snapshot_semantic_revision = str(
        source_meta.get("serenity_semantic_revision") or ""
    )
    if not snapshot_target_id:
        return "current_serenity_target_missing", current
    if not snapshot_semantic_revision:
        return "current_serenity_semantic_revision_missing", current
    if not bool(current.get("target_matches")):
        return "current_serenity_target_replaced", current
    if not bool(current.get("certificate_current")):
        return "current_serenity_target_not_ready", current
    current_semantic_revision = str(current.get("semantic_revision") or "")
    if not current_semantic_revision:
        return "current_serenity_semantic_revision_missing", current
    if current_semantic_revision != snapshot_semantic_revision:
        return "current_serenity_semantic_revision_changed", current
    target = dict(source_meta.get("serenity_candidate_target") or {})
    policy = dict(source_meta.get("serenity_policy_snapshot") or {})
    try:
        comparisons = {
            "mode": str(policy.get("mode") or ""),
            "formula_version": str(
                source_meta.get("serenity_formula_version") or ""
            ),
            "target_id": snapshot_target_id,
            "target_input_hash": str(target.get("input_hash") or ""),
            "activation_observed_at": str(
                target.get("activation_observed_at") or ""
            ),
            "activation_revision": str(
                target.get("activation_revision") or ""
            ),
            "policy_state": str(policy.get("state") or ""),
            "policy_epoch": int(policy.get("epoch") or 0),
            "policy_applied_weight": float(
                policy.get("applied_weight") or 0.0
            ),
            "policy_max_weight": float(policy.get("max_weight") or 0.0),
            "native_required": policy.get("native_required") is True,
        }
    except (TypeError, ValueError):
        return "current_serenity_attestation_changed", current
    if any(current.get(key) != value for key, value in comparisons.items()):
        return "current_serenity_attestation_changed", current
    if not bool(current.get("available")):
        return "current_serenity_runtime_unavailable", current
    return None, current


def _day(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:8]


def _serenity(pick: AdvicePick) -> dict[str, Any]:
    return dict(
        (pick.explain_context or {}).get("serenity")
        or (pick.meta or {}).get("serenity")
        or {}
    )


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _close(left: Any, right: Any) -> bool:
    left_value = _finite(left)
    right_value = _finite(right)
    return bool(
        left_value is not None
        and right_value is not None
        and abs(left_value - right_value) <= _TOLERANCE
    )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _parse_iso(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _runtime_binding_error(
    snapshot: Any,
    meta: dict[str, Any],
    *,
    reference_required: bool,
) -> str | None:
    binding = dict(meta.get("runtime_evidence_binding") or {})
    if not binding:
        return None
    decision_context_snapshot_id = str(
        meta.get("decision_context_snapshot_id") or ""
    )
    reference_id = str(meta.get("serenity_reference_snapshot_id") or "")
    policy = dict(meta.get("serenity_policy_snapshot") or {})
    payload_hash = str(binding.get("decision_snapshot_payload_hash") or "")
    try:
        policy_epoch = int(policy.get("epoch"))
        bound_epoch = int(binding.get("policy_epoch"))
    except (TypeError, ValueError):
        return "native_snapshot_runtime_binding_invalid"
    if (
        str(binding.get("schema") or "") != "RuntimeEvidenceBinding.v1"
        or str(binding.get("decision_context_snapshot_id") or "")
        != decision_context_snapshot_id
        or len(payload_hash) != 64
        or any(char not in "0123456789abcdef" for char in payload_hash)
        or str(binding.get("formula_version") or "")
        != str(meta.get("serenity_formula_version") or "")
        or bound_epoch != policy_epoch
        or _day(binding.get("decision_trade_day"))
        != _day(getattr(snapshot, "decision_trade_day", None))
        or _day(binding.get("daybook_effective_day"))
        != _day(getattr(snapshot, "daybook_effective_day", None))
        or _parse_iso(binding.get("decision_observed_at")) is None
        or str(binding.get("serenity_reference_snapshot_id") or "")
        != reference_id
    ):
        return "native_snapshot_runtime_binding_invalid"
    if reference_required and (
        not reference_id
        or not str(binding.get("serenity_reference_input_checksum") or "")
        or not str(binding.get("serenity_pending_id") or "")
    ):
        return "native_snapshot_runtime_binding_incomplete"
    if not reference_id and (
        binding.get("serenity_reference_input_checksum") is not None
        or binding.get("serenity_pending_id") is not None
    ):
        return "native_snapshot_runtime_binding_invalid"
    return None


def _validate_attested_candidate(
    symbol: str,
    record: dict[str, Any],
    *,
    target_id: str,
    source_run_id: str,
    readiness_revision: str,
    semantic_revision: str,
    activation_observed_at: str,
    activation_revision: str,
    poll_finished_at: str,
    poll_expires_at: str,
    policy: dict[str, Any],
    snapshot_observed_at: str,
) -> str | None:
    required = {
        "status",
        "target_id",
        "source_run_id",
        "readiness_revision",
        "semantic_revision",
        "input_hash",
        "decision_at",
        "lineage",
        "availability",
        "direction",
        "confidence",
        "source_quality",
        "evidence_count",
        "facts",
        "fact_ids",
        "learning_eligible",
        "alpha_value",
        "scored",
    }
    if any(key not in record or record.get(key) is None for key in required):
        return f"native_snapshot_attestation_payload_invalid:{symbol}"
    status = str(record.get("status") or "")
    if status not in {"available", "no_relevant_evidence"}:
        return f"native_snapshot_alpha_status_invalid:{symbol}"
    if (
        str(record.get("target_id") or "") != target_id
        or str(record.get("source_run_id") or "") != source_run_id
        or str(record.get("readiness_revision") or "") != readiness_revision
        or str(record.get("semantic_revision") or "") != semantic_revision
        or not str(record.get("input_hash") or "")
    ):
        return f"native_snapshot_alpha_lineage_invalid:{symbol}"
    lineage = dict(record.get("lineage") or {})
    if (
        str(lineage.get("target_id") or "") != target_id
        or str(lineage.get("source_run_id") or "") != source_run_id
        or str(lineage.get("readiness_revision") or "") != readiness_revision
        or str(lineage.get("activation_observed_at") or "")
        != activation_observed_at
        or str(lineage.get("activation_revision") or "")
        != activation_revision
        or str(lineage.get("poll_finished_at") or "") != poll_finished_at
        or str(lineage.get("poll_expires_at") or "") != poll_expires_at
    ):
        return f"native_snapshot_alpha_lineage_invalid:{symbol}"
    fact_ids = {str(item) for item in list(record.get("fact_ids") or []) if str(item)}
    raw_fact_ids = [
        str(item) for item in list(record.get("fact_ids") or []) if str(item)
    ]
    try:
        facts = [
            SerenityFact.model_validate(item)
            for item in list(record.get("facts") or [])
        ]
    except Exception:
        return f"native_snapshot_alpha_facts_invalid:{symbol}"
    if (
        raw_fact_ids != [fact.fact_id for fact in facts]
        or len(raw_fact_ids) != len(fact_ids)
        or any(
            fact.symbol != symbol
            or fact.verification_state != "verified"
            or float(fact.source_quality) < 0.999
            for fact in facts
        )
    ):
        return f"native_snapshot_alpha_facts_invalid:{symbol}"
    fact_lineage = dict(lineage.get("facts") or {})
    if fact_ids - set(fact_lineage):
        return f"native_snapshot_alpha_fact_lineage_invalid:{symbol}"
    required_fact_lineage = {
        "document_id",
        "version_id",
        "content_hash",
        "document_first_seen_at",
        "version_first_seen_at",
    }
    if any(
        not required_fact_lineage.issubset(
            {
                key
                for key, value in dict(fact_lineage.get(fact_id) or {}).items()
                if str(value or "")
            }
        )
        for fact_id in fact_ids
    ):
        return f"native_snapshot_alpha_fact_lineage_invalid:{symbol}"
    decision_clock = _parse_iso(record.get("decision_at"))
    snapshot_clock = _parse_iso(snapshot_observed_at)
    activation_clock = _parse_iso(activation_observed_at)
    poll_finished_clock = _parse_iso(poll_finished_at)
    poll_expires_clock = _parse_iso(poll_expires_at)
    if (
        decision_clock is None
        or snapshot_clock is None
        or activation_clock is None
        or poll_finished_clock is None
        or poll_expires_clock is None
        or decision_clock != snapshot_clock
        or activation_clock > poll_finished_clock
        or poll_finished_clock > decision_clock
        or decision_clock > poll_expires_clock
    ):
        return f"native_snapshot_alpha_time_lineage_invalid:{symbol}"
    evidence_ttl = timedelta(
        days=max(1, int(load_config().serenity.evidence_ttl_days))
    )
    for fact in facts:
        published_at = _parse_iso(fact.published_at)
        effective_at = _parse_iso(fact.effective_available_at)
        lineage_item = dict(fact_lineage.get(fact.fact_id) or {})
        document_seen = _parse_iso(lineage_item.get("document_first_seen_at"))
        version_seen = _parse_iso(lineage_item.get("version_first_seen_at"))
        if (
            published_at is None
            or effective_at is None
            or document_seen is None
            or version_seen is None
            or published_at > decision_clock
            or effective_at > decision_clock
            or document_seen > decision_clock
            or version_seen > decision_clock
            or decision_clock - published_at > evidence_ttl
            or str(lineage_item.get("document_id") or "")
            != str(fact.source_document_id or "")
            or str(lineage_item.get("version_id") or "")
            != str(fact.source_version_id or "")
            or str(lineage_item.get("content_hash") or "")
            != str(fact.content_sha256 or "")
        ):
            return f"native_snapshot_alpha_fact_lineage_invalid:{symbol}"
    alpha = _finite(record.get("alpha_value"))
    confidence = _finite(record.get("confidence"))
    source_quality = _finite(record.get("source_quality"))
    try:
        availability = int(record.get("availability"))
        direction = int(record.get("direction"))
        evidence_count = int(record.get("evidence_count"))
    except (TypeError, ValueError):
        return f"native_snapshot_alpha_numeric_invalid:{symbol}"
    if (
        alpha is None
        or alpha < -1.0
        or alpha > 1.0
        or confidence is None
        or confidence < 0.0
        or confidence > 1.0
        or source_quality is None
        or source_quality < 0.0
        or source_quality > 1.0
        or availability not in {0, 1}
        or direction not in {-1, 0, 1}
        or evidence_count != len(facts)
    ):
        return f"native_snapshot_alpha_numeric_invalid:{symbol}"
    if status == "no_relevant_evidence" and abs(alpha) > _TOLERANCE:
        return f"native_snapshot_neutral_alpha_nonzero:{symbol}"
    if not bool(record.get("learning_eligible")) and abs(alpha) > _TOLERANCE:
        return f"native_snapshot_ineligible_alpha_nonzero:{symbol}"
    live_directional = [
        fact
        for fact in facts
        if int(fact.direction) != 0 and not bool(fact.backfill_only)
    ]
    expected_status = (
        "available" if live_directional else "no_relevant_evidence"
    )
    expected_alpha = (
        sum(
            float(fact.direction)
            * float(fact.confidence)
            * float(fact.source_quality)
            for fact in live_directional
        )
        / max(1, len(live_directional))
    )
    expected_alpha = max(-1.0, min(1.0, expected_alpha))
    expected_availability = 1 if live_directional else 0
    expected_direction = (
        -1 if expected_alpha < -_TOLERANCE
        else 1 if expected_alpha > _TOLERANCE
        else 0
    )
    expected_confidence = (
        min(
            1.0,
            sum(
                abs(
                    float(fact.direction)
                    * float(fact.confidence)
                    * float(fact.source_quality)
                )
                for fact in live_directional
            )
            / max(1, len(live_directional)),
        )
        if live_directional
        else 0.0
    )
    expected_source_quality = (
        sum(float(fact.source_quality) for fact in live_directional)
        / len(live_directional)
        if live_directional
        else 0.0
    )
    if (
        status != expected_status
        or availability != expected_availability
        or direction != expected_direction
        or not _close(confidence, expected_confidence)
        or not _close(source_quality, expected_source_quality)
        or bool(record.get("learning_eligible")) != bool(live_directional)
        or not _close(alpha, expected_alpha)
    ):
        return f"native_snapshot_alpha_formula_mismatch:{symbol}"
    decision_at = str(record.get("decision_at") or "")
    expected_input_hash = sha256(
        json.dumps(
            {
                "symbol": symbol,
                "decision_at": decision_at,
                "target_id": target_id,
                "status": status,
                "alpha_value": expected_alpha,
                "facts": [fact.model_dump(mode="json") for fact in facts],
                "lineage": lineage,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if str(record.get("input_hash") or "") != expected_input_hash:
        return f"native_snapshot_alpha_input_hash_mismatch:{symbol}"

    if not bool(record.get("scored")):
        evidence = dict(record.get("exclusion_evidence") or {})
        expected_exclusion = ""
        if bool(evidence.get("market_hard_block")):
            reasons = list(evidence.get("market_hard_block_reasons") or [])
            expected_exclusion = str(reasons[0]) if reasons else "market_context_hard_block"
        elif bool(evidence.get("candidate_hard_block")):
            reasons = list(evidence.get("candidate_hard_block_reasons") or [])
            expected_exclusion = str(reasons[0]) if reasons else "candidate_hard_block"
        elif bool(evidence.get("risk_hard_block")):
            reasons = list(evidence.get("risk_hard_block_reasons") or [])
            expected_exclusion = str(reasons[0]) if reasons else "risk_hard_block"
        if (
            not expected_exclusion
            or str(record.get("exclusion_reason") or "") != expected_exclusion
        ):
            return f"native_snapshot_unscored_candidate_unexplained:{symbol}"
        return None

    numeric_keys = (
        "effective_weight",
        "score_contribution",
        "baseline_adaptive_score",
        "decision_score",
    )
    numeric = {key: _finite(record.get(key)) for key in numeric_keys}
    if any(value is None for value in numeric.values()):
        return f"native_snapshot_alpha_numeric_invalid:{symbol}"
    weight = float(numeric["effective_weight"])
    contribution = float(numeric["score_contribution"])
    baseline = float(numeric["baseline_adaptive_score"])
    decision = float(numeric["decision_score"])
    max_weight = _finite(policy.get("max_weight"))
    if (
        max_weight is None
        or max_weight < 0.0
        or max_weight > 0.08 + _TOLERANCE
        or weight < 0.0
        or weight > max_weight + _TOLERANCE
    ):
        return f"native_snapshot_serenity_weight_invalid:{symbol}"
    policy_state = str(policy.get("state") or "")
    if str(record.get("policy_state") or "") != policy_state:
        return f"native_snapshot_serenity_policy_state_mismatch:{symbol}"
    expected_weight = (
        _finite(policy.get("applied_weight"))
        if policy_state in {"probation", "active"}
        else 0.0
    )
    if expected_weight is None or not _close(weight, expected_weight):
        return f"native_snapshot_serenity_weight_policy_mismatch:{symbol}"
    if not _close(contribution, weight * alpha):
        return f"native_snapshot_serenity_contribution_mismatch:{symbol}"
    if bool(record.get("non_binding")) != (abs(contribution) <= _TOLERANCE):
        return f"native_snapshot_serenity_binding_flag_invalid:{symbol}"

    expert_scores = dict(record.get("expert_scores") or {})
    expert_weights = dict(record.get("expert_weights") or {})
    expert_contributions = dict(record.get("expert_contributions") or {})
    if (
        set(expert_scores) != _EXPERT_KEYS
        or set(expert_weights) != set(_BASE_EXPERT_KEYS)
        or set(expert_contributions) != _EXPERT_KEYS
    ):
        return f"native_snapshot_expert_vector_invalid:{symbol}"
    if not _close(expert_scores.get("serenity"), alpha):
        return f"native_snapshot_serenity_expert_score_mismatch:{symbol}"
    if not _close(expert_contributions.get("serenity"), contribution):
        return f"native_snapshot_serenity_expert_contribution_mismatch:{symbol}"
    score_values = {key: _finite(value) for key, value in expert_scores.items()}
    weight_values = {
        key: _finite(value) for key, value in expert_weights.items()
    }
    contribution_values = {
        key: _finite(value) for key, value in expert_contributions.items()
    }
    if (
        any(value is None for value in score_values.values())
        or any(value is None for value in weight_values.values())
        or any(value is None for value in contribution_values.values())
        or any(
            float(score_values[key]) < 0.0
            or float(score_values[key]) > 1.0
            for key in _BASE_EXPERT_KEYS
        )
        or any(
            float(weight_values[key]) < 0.03 - _TOLERANCE
            or float(weight_values[key]) > 0.45 + _TOLERANCE
            for key in _BASE_EXPERT_KEYS
        )
        or not _close(sum(float(value) for value in weight_values.values()), 1.0)
    ):
        return f"native_snapshot_expert_vector_invalid:{symbol}"
    for key in _BASE_EXPERT_KEYS:
        expected_contribution = (
            -float(weight_values[key]) * float(score_values[key])
            if key == "risk"
            else float(weight_values[key]) * float(score_values[key])
        )
        if not _close(contribution_values[key], expected_contribution):
            return f"native_snapshot_expert_contribution_mismatch:{symbol}:{key}"
    expected_decision = _clamp(
        sum(float(value) for value in contribution_values.values())
    )
    expected_baseline = _clamp(
        sum(
            float(value)
            for key, value in contribution_values.items()
            if key != "serenity"
        )
    )
    if not _close(decision, expected_decision):
        return f"native_snapshot_decision_score_formula_mismatch:{symbol}"
    if not _close(baseline, expected_baseline):
        return f"native_snapshot_baseline_score_formula_mismatch:{symbol}"
    return None


def native_snapshot_integrity_errors(snapshot: Any, book: MarketBook) -> list[str]:
    """Validate the full target, lineage and ninth-expert score attestation."""

    meta = dict(book.daybook.source_meta or {})
    if str(meta.get("selection_policy") or "") != SELECTION_POLICY:
        return ["native_snapshot_policy_incompatible"]
    if not producer_is_compatible(book.daybook.producer):
        return ["native_snapshot_producer_incompatible"]
    if bool(getattr(snapshot, "tradeable", False)) and str(
        book.gate.state or ""
    ).upper() != "ALLOW":
        return ["native_snapshot_tradeable_gate_invalid"]
    decision_context_snapshot_id = str(
        meta.get("decision_context_snapshot_id") or ""
    )
    if not decision_context_snapshot_id:
        return ["native_snapshot_decision_context_missing"]
    binding_error = _runtime_binding_error(
        snapshot,
        meta,
        reference_required=bool(book.daybook.picks),
    )
    if binding_error:
        return [binding_error]
    target_id = str(meta.get("serenity_target_id") or "")
    if not target_id:
        return ["native_snapshot_target_missing"]
    if meta.get("serenity_native_ready") is not True:
        return ["native_snapshot_alpha_incomplete"]

    target = dict(meta.get("serenity_candidate_target") or {})
    activation_observed_at = str(
        target.get("activation_observed_at") or ""
    )
    activation_revision = str(target.get("activation_revision") or "")
    target_symbols = {
        str(symbol or "").strip()
        for symbol in list(target.get("symbols") or [])
        if str(symbol or "").strip()
    }
    if (
        str(target.get("target_id") or "") != target_id
        or not target_symbols
        or not activation_observed_at
        or not activation_revision
        or len(list(target.get("symbols") or [])) != len(target_symbols)
        or _day(target.get("decision_trade_day"))
        != _day(getattr(snapshot, "decision_trade_day", None))
        or _day(target.get("daybook_effective_day"))
        != _day(getattr(snapshot, "daybook_effective_day", None))
    ):
        return ["native_snapshot_target_lineage_incomplete"]
    expected_hash = candidate_target_identity_hash(
        target_symbols,
        decision_trade_day=str(target.get("decision_trade_day") or ""),
        daybook_effective_day=str(target.get("daybook_effective_day") or ""),
    )
    if (
        str(target.get("input_hash") or "") != expected_hash
        or target_id != "sertarget_" + expected_hash[:24]
    ):
        return ["native_snapshot_target_identity_invalid"]

    formula_version = str(meta.get("serenity_formula_version") or "")
    source_run_id = str(meta.get("serenity_source_run_id") or "")
    readiness_revision = str(meta.get("serenity_readiness_revision") or "")
    semantic_revision = str(meta.get("serenity_semantic_revision") or "")
    poll_finished_at = str(meta.get("serenity_poll_finished_at") or "")
    poll_expires_at = str(meta.get("serenity_poll_expires_at") or "")
    policy = dict(meta.get("serenity_policy_snapshot") or {})
    attestation = dict(meta.get("serenity_native_attestation") or {})
    policy_state = str(policy.get("state") or "")
    policy_epoch = _finite(policy.get("epoch"))
    policy_applied_weight = _finite(policy.get("applied_weight"))
    policy_max_weight = _finite(policy.get("max_weight"))
    if (
        formula_version != NATIVE_SERENITY_FORMULA_VERSION
        or str(policy.get("formula_version") or "") != formula_version
        or str(policy.get("mode") or "") != "native"
        or policy.get("native_required") is not True
        or policy_state
        not in {"warming", "shadow", "probation", "active", "suspended", "off"}
        or policy_epoch is None
        or policy_epoch < 1
        or policy_applied_weight is None
        or policy_max_weight is None
        or policy_applied_weight < 0.0
        or policy_max_weight < 0.0
        or policy_applied_weight > policy_max_weight + _TOLERANCE
        or policy_max_weight > 0.08 + _TOLERANCE
        or not source_run_id
        or not readiness_revision
        or not semantic_revision
        or not poll_finished_at
        or not poll_expires_at
    ):
        return ["native_snapshot_policy_attestation_invalid"]
    if (
        str(attestation.get("schema") or "") != "SerenityNativeAttestation.v1"
        or str(attestation.get("formula_version") or "") != formula_version
        or str(attestation.get("target_id") or "") != target_id
        or str(attestation.get("target_input_hash") or "") != expected_hash
        or str(attestation.get("activation_observed_at") or "")
        != activation_observed_at
        or str(attestation.get("activation_revision") or "")
        != activation_revision
        or str(attestation.get("source_run_id") or "") != source_run_id
        or str(attestation.get("readiness_revision") or "")
        != readiness_revision
        or str(attestation.get("semantic_revision") or "")
        != semantic_revision
        or str(attestation.get("poll_finished_at") or "") != poll_finished_at
        or str(attestation.get("poll_expires_at") or "") != poll_expires_at
        or dict(attestation.get("policy_snapshot") or {}) != policy
    ):
        return ["native_snapshot_attestation_lineage_invalid"]

    candidates = {
        str(symbol): dict(value or {})
        for symbol, value in dict(attestation.get("candidates") or {}).items()
    }
    if set(candidates) != target_symbols:
        return ["native_snapshot_attestation_target_coverage_invalid"]
    runtime_binding = dict(meta.get("runtime_evidence_binding") or {})
    decision_observed_at = str(
        runtime_binding.get("decision_observed_at")
        or getattr(snapshot, "observed_at", None)
        or getattr(snapshot, "as_of", None)
        or ""
    )
    semantic_signals: dict[str, FrozenSerenitySignal] = {}
    for symbol in sorted(target_symbols):
        error = _validate_attested_candidate(
            symbol,
            candidates[symbol],
            target_id=target_id,
            source_run_id=source_run_id,
            readiness_revision=readiness_revision,
            semantic_revision=semantic_revision,
            activation_observed_at=activation_observed_at,
            activation_revision=activation_revision,
            poll_finished_at=poll_finished_at,
            poll_expires_at=poll_expires_at,
            policy=policy,
            snapshot_observed_at=decision_observed_at,
        )
        if error:
            return [error]
        record = candidates[symbol]
        try:
            semantic_signals[symbol] = FrozenSerenitySignal(
                symbol=symbol,
                status=str(record.get("status") or "not_ready"),
                availability=int(record.get("availability") or 0),
                learning_eligible=bool(record.get("learning_eligible")),
                direction=int(record.get("direction") or 0),
                confidence=float(record.get("confidence") or 0.0),
                source_quality=float(record.get("source_quality") or 0.0),
                alpha_value=float(record.get("alpha_value") or 0.0),
                decision_at=str(record.get("decision_at") or ""),
                generated_at=str(record.get("decision_at") or ""),
                target_id=str(record.get("target_id") or ""),
                source_run_id=str(record.get("source_run_id") or ""),
                evidence_count=int(record.get("evidence_count") or 0),
                fact_ids=[str(item) for item in list(record.get("fact_ids") or [])],
                facts=[
                    SerenityFact.model_validate(item)
                    for item in list(record.get("facts") or [])
                ],
                lineage=dict(record.get("lineage") or {}),
                input_hash=str(record.get("input_hash") or ""),
            )
        except Exception:
            return [f"native_snapshot_semantic_payload_invalid:{symbol}"]
    recomputed_semantic_revision = serenity_batch_semantic_revision(
        semantic_signals,
        target_id=target_id,
        target_input_hash=expected_hash,
        activation_observed_at=activation_observed_at,
        activation_revision=activation_revision,
        formula_version=formula_version,
        policy_snapshot=policy,
    )
    if recomputed_semantic_revision != semantic_revision:
        return ["native_snapshot_semantic_revision_invalid"]

    scored = {
        symbol: record for symbol, record in candidates.items() if record.get("scored")
    }
    ranked_symbols = [str(item) for item in list(attestation.get("ranked_symbols") or [])]
    expected_ranked = [
        symbol
        for symbol, _ in sorted(
            scored.items(),
            key=lambda item: (
                -float(item[1].get("decision_score") or 0.0),
                item[0],
            ),
        )
    ]
    if ranked_symbols != expected_ranked or len(ranked_symbols) != len(set(ranked_symbols)):
        return ["native_snapshot_attested_ranking_invalid"]
    decision = str(attestation.get("decision") or "")
    selected_symbols = [
        str(item) for item in list(attestation.get("selected_symbols") or [])
    ]
    topk = max(0, int(attestation.get("topk") or 0))
    try:
        configured_topk = int(meta.get("topk"))
    except (TypeError, ValueError):
        configured_topk = -1
    if topk <= 0 or configured_topk != topk:
        return ["native_snapshot_attested_topk_invalid"]
    expected_selected = expected_ranked[:topk] if decision == "recommend" else []
    daybook_selected = [pick.symbol for pick in book.daybook.picks]
    if (
        decision not in {"recommend", "no_trade"}
        or (decision == "no_trade" and bool(expected_ranked))
        or decision != str(meta.get("decision") or "")
        or decision != str(getattr(snapshot, "decision", "") or "")
        or selected_symbols != expected_selected
        or daybook_selected != selected_symbols
    ):
        return ["native_snapshot_attested_topk_invalid"]

    try:
        reserve_count = int(meta.get("reserve_count") or 0)
    except (TypeError, ValueError):
        reserve_count = -1
    expected_reserve = (
        expected_ranked[topk : topk + reserve_count]
        if decision == "recommend" and reserve_count >= 0
        else []
    )
    if (
        reserve_count < 0
        or [str(item) for item in list(book.daybook.reserve_symbols or [])]
        != expected_reserve
        or [pick.symbol for pick in book.daybook.reserve_picks]
        != expected_reserve
    ):
        return ["native_snapshot_reserve_projection_invalid"]
    board_symbols = [entry.symbol for entry in book.board]
    # The daily decision's selected_symbols order is immutable selection
    # authority.  A live board is a separate execution projection: it may
    # reorder those same symbols as intraday readiness changes.  Publishing
    # must still cover exactly the selected set, while entry.pick retains the
    # immutable decision rank checked below.
    if len(board_symbols) != len(set(board_symbols)) or set(board_symbols) != set(selected_symbols):
        return ["native_snapshot_board_projection_invalid"]
    projected_picks = [
        *book.daybook.picks,
        *book.daybook.reserve_picks,
        *(entry.pick for entry in book.board),
    ]
    if any(pick.symbol not in target_symbols for pick in projected_picks):
        return ["native_snapshot_candidate_outside_target"]
    for pick in projected_picks:
        record = candidates.get(pick.symbol) or {}
        expected_rank = expected_ranked.index(pick.symbol) + 1
        if (
            int(pick.rank or 0) != expected_rank
            or str(pick.decision_context_snapshot_id or "")
            != decision_context_snapshot_id
        ):
            return [f"native_snapshot_pick_projection_invalid:{pick.symbol}"]
        if not bool(record.get("scored")):
            return [f"native_snapshot_unscored_candidate_projected:{pick.symbol}"]
        alpha = _serenity(pick)
        required = (
            "status",
            "target_id",
            "source_run_id",
            "input_hash",
            "lineage",
            "alpha_value",
            "effective_weight",
            "score_contribution",
            "decision_score",
            "non_binding",
            "learning_eligible",
        )
        if any(key not in alpha or alpha.get(key) is None for key in required):
            return [f"native_snapshot_alpha_payload_invalid:{pick.symbol}"]
        for key in (
            "status",
            "target_id",
            "source_run_id",
            "input_hash",
            "lineage",
            "fact_ids",
            "policy_state",
            "non_binding",
            "learning_eligible",
        ):
            if alpha.get(key) != record.get(key):
                return [f"native_snapshot_pick_attestation_mismatch:{pick.symbol}:{key}"]
        for key in (
            "alpha_value",
            "effective_weight",
            "score_contribution",
            "decision_score",
        ):
            if not _close(alpha.get(key), record.get(key)):
                return [f"native_snapshot_pick_attestation_mismatch:{pick.symbol}:{key}"]
        adaptive = dict((pick.meta or {}).get("adaptive_policy") or {})
        if (
            dict(adaptive.get("expert_scores") or {})
            != dict(record.get("expert_scores") or {})
            or dict(adaptive.get("expert_contributions") or {})
            != dict(record.get("expert_contributions") or {})
            or dict(adaptive.get("expert_weights") or {})
            != dict(record.get("expert_weights") or {})
            or not _close(adaptive.get("serenity_adjustment"), record.get("score_contribution"))
            or not _close(adaptive.get("serenity_alpha_value"), record.get("alpha_value"))
            or not _close((pick.scores or {}).get("final"), record.get("decision_score"))
            or not _close((pick.scores or {}).get("serenity_adjustment"), record.get("score_contribution"))
            or not _close((pick.scores or {}).get("serenity_alpha"), record.get("alpha_value"))
        ):
            return [f"native_snapshot_pick_math_projection_invalid:{pick.symbol}"]

    for entry in book.board:
        if entry.symbol not in target_symbols:
            return ["native_snapshot_candidate_outside_target"]
        entry_serenity = dict((entry.explain_context or {}).get("serenity") or {})
        if entry_serenity != _serenity(entry.pick):
            return [f"native_snapshot_board_serenity_mirror_invalid:{entry.symbol}"]
        record = candidates.get(entry.symbol) or {}
        expected_final = (
            float(entry.pulse.live_score)
            if entry.pulse is not None and float(entry.pulse.live_score or 0.0)
            else float(record.get("decision_score") or 0.0)
        )
        if (
            int(entry.pick.rank or 0) != expected_ranked.index(entry.symbol) + 1
            or not _close(entry.final_score, expected_final)
        ):
            return [f"native_snapshot_board_projection_invalid:{entry.symbol}"]
    return []


def pending_native_snapshot_integrity_errors(
    snapshot: Any, book: MarketBook
) -> list[str]:
    """Validate a fail-closed native snapshot that has no publishable ranking."""

    meta = dict(book.daybook.source_meta or {})
    if str(meta.get("selection_policy") or "") != SELECTION_POLICY:
        return ["native_snapshot_policy_incompatible"]
    if not producer_is_compatible(book.daybook.producer):
        return ["native_snapshot_producer_incompatible"]
    if (
        str(getattr(snapshot, "decision", "") or "") != "no_trade"
        or str(meta.get("decision") or "") != "no_trade"
        or meta.get("serenity_native_ready") is not False
        or bool(book.daybook.tradeable)
        or bool(book.daybook.picks)
        or bool(book.daybook.reserve_picks)
        or bool(book.daybook.reserve_symbols)
        or bool(book.board)
    ):
        return ["native_snapshot_pending_payload_invalid"]
    if (
        str(meta.get("serenity_formula_version") or "")
        != NATIVE_SERENITY_FORMULA_VERSION
        or not str(meta.get("decision_context_snapshot_id") or "")
        or bool(meta.get("serenity_native_attestation"))
        or bool(meta.get("serenity_readiness_revision"))
    ):
        return ["native_snapshot_pending_contract_incomplete"]
    binding_error = _runtime_binding_error(
        snapshot,
        meta,
        reference_required=False,
    )
    if binding_error:
        return [binding_error]
    policy = dict(meta.get("serenity_policy_snapshot") or {})
    epoch = _finite(policy.get("epoch"))
    applied_weight = _finite(policy.get("applied_weight"))
    max_weight = _finite(policy.get("max_weight"))
    if (
        str(policy.get("formula_version") or "")
        != NATIVE_SERENITY_FORMULA_VERSION
        or str(policy.get("mode") or "") != "native"
        or policy.get("native_required") is not True
        or str(policy.get("state") or "")
        not in {"warming", "shadow", "probation", "active", "suspended", "off"}
        or epoch is None
        or epoch < 1
        or applied_weight is None
        or max_weight is None
        or applied_weight < 0.0
        or applied_weight > max_weight + _TOLERANCE
        or max_weight < 0.0
        or max_weight > 0.08 + _TOLERANCE
    ):
        return ["native_snapshot_pending_policy_invalid"]
    target_id = str(meta.get("serenity_target_id") or "")
    target = dict(meta.get("serenity_candidate_target") or {})
    if not target_id:
        if target:
            return ["native_snapshot_pending_target_invalid"]
        return []
    symbols = [
        str(symbol or "").strip()
        for symbol in list(target.get("symbols") or [])
        if str(symbol or "").strip()
    ]
    if (
        str(target.get("target_id") or "") != target_id
        or not symbols
        or len(symbols) != len(set(symbols))
        or not str(target.get("activation_observed_at") or "")
        or not str(target.get("activation_revision") or "")
        or _day(target.get("decision_trade_day"))
        != _day(getattr(snapshot, "decision_trade_day", None))
        or _day(target.get("daybook_effective_day"))
        != _day(getattr(snapshot, "daybook_effective_day", None))
    ):
        return ["native_snapshot_pending_target_invalid"]
    target_hash = candidate_target_identity_hash(
        symbols,
        decision_trade_day=str(target.get("decision_trade_day") or ""),
        daybook_effective_day=str(target.get("daybook_effective_day") or ""),
    )
    if (
        str(target.get("input_hash") or "") != target_hash
        or target_id != "sertarget_" + target_hash[:24]
    ):
        return ["native_snapshot_pending_target_invalid"]
    return []
