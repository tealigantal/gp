from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Iterable, List

from ..contracts.objects import CanonicalPick, DecisionContextModel, DecisionSynthesis, EvidencePack, ThesisLifecycle
from ..llm.client import LLMClient


ALLOWED_ACTIONS = {"HOLD", "ADD", "REDUCE", "EXIT", "WAIT", "NO_TRADE"}
THESIS_STATES = {"thesis_strengthened", "thesis_unchanged", "thesis_weakening", "thesis_invalidated"}


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except Exception:
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _clamp(value: Any, *, default: float = 0.0) -> float:
    out = _safe_float(value, default)
    if out is None:
        out = default
    return max(0.0, min(1.0, float(out)))


def _model_dump(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        try:
            obj = value.model_dump()
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _pick_field(pick: Any, key: str, default: Any = None) -> Any:
    if pick is None:
        return default
    if isinstance(pick, dict):
        return pick.get(key, default)
    return getattr(pick, key, default)


def objective_from_frame(frame: Any) -> str:
    request = str(getattr(frame, "request", "") or "").strip()
    subject = str(getattr(frame, "subject", "") or "").strip()
    if request == "exit_decision" or subject == "holding":
        return "manage_existing_position"
    if request in {"live_entry_check", "intraday_situation", "recommend"}:
        return "open_or_add_position"
    if request in {"compare", "candidate_compare"}:
        return "compare_alternatives"
    if request == "run_change":
        return "audit_previous_decision"
    if request in {"pick_detail", "single_stock_query"}:
        return "evaluate_security_decision"
    if request == "no_trade_explain":
        return "evaluate_no_trade_decision"
    return "evaluate_decision"


def _numeric_values(text: str) -> List[float]:
    out: List[float] = []
    for match in re.finditer(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", str(text or "")):
        value = _safe_float(match.group(1))
        if value is not None:
            out.append(value)
    return out[:8]


def _market_context(evidence: EvidencePack, run: Any) -> Dict[str, Any]:
    book = evidence.book
    run_obj = run if run is not None else evidence.active_run
    return {
        "trading_day": book.trading_day,
        "daybook_effective_day": book.daybook_effective_day or book.daybook.trading_day,
        "market_phase": book.market_phase,
        "slot_status": book.slot_status,
        "pulse_trade_day": book.pulse_trade_day,
        "pulse_slot_at": book.pulse_slot_at,
        "gate": _model_dump(book.gate),
        "data_quality": _model_dump(book.data_quality),
        "book_version": book.book_version,
        "run_id": getattr(run_obj, "run_id", None),
        "run_action": getattr(run_obj, "run_action", None),
        "recommendation_state": getattr(run_obj, "recommendation_state", None),
        "publish_allowed": getattr(run_obj, "publish_allowed", book.publish_allowed),
    }


def _security_context(pick: Any, candidates: Iterable[Any] | None = None) -> Dict[str, Any]:
    probability = dict(_pick_field(pick, "probability", {}) or {})
    risk = dict(_pick_field(pick, "risk", {}) or {})
    ranking = dict(_pick_field(pick, "ranking", {}) or {})
    meta = dict(_pick_field(pick, "meta", {}) or {})
    explain_context = dict(_pick_field(pick, "explain_context", {}) or {})
    adaptive_policy = dict(
        _pick_field(pick, "adaptive_policy", {}) or meta.get("adaptive_policy") or explain_context.get("adaptive_policy") or {}
    )
    evidence = dict(probability.get("evidence") or {})
    plan = dict(_pick_field(pick, "execution_plan", {}) or {})
    if not plan:
        plan = {
            "entry": _pick_field(pick, "entry_zone", {}),
            "stop": _pick_field(pick, "stop"),
            "take_profit": _pick_field(pick, "take_profit", []),
        }
    peers = []
    for item in list(candidates or [])[:8]:
        peers.append(
            {
                "symbol": _pick_field(item, "symbol"),
                "rank": _pick_field(item, "rank"),
                "ranking_score": (dict(_pick_field(item, "ranking", {}) or {}).get("ranking_score")),
                "up_probability_3d": (dict(_pick_field(item, "probability", {}) or {}).get("up_probability_3d")),
                "decision_action": _pick_field(item, "decision_action"),
            }
        )
    return {
        "symbol": _pick_field(pick, "symbol"),
        "name": _pick_field(pick, "name"),
        "rank": _pick_field(pick, "rank"),
        "action": _pick_field(pick, "action"),
        "execution_state": _pick_field(pick, "execution_state"),
        "recommendation_state": _pick_field(pick, "recommendation_state"),
        "can_execute_now": bool(_pick_field(pick, "can_execute_now", False)),
        "entry_zone": _pick_field(pick, "entry_zone", {}),
        "entry_text": _pick_field(pick, "entry_text"),
        "stop": _pick_field(pick, "stop"),
        "stop_text": _pick_field(pick, "stop_text"),
        "take_profit": _pick_field(pick, "take_profit", []),
        "take_text": _pick_field(pick, "take_text"),
        "probability": probability,
        "risk": risk,
        "ranking": ranking,
        "historical_cases": list(_pick_field(pick, "historical_cases", []) or [])[:8],
        "evidence": {
            "sample_size": evidence.get("sample_size"),
            "effective_sample_size": evidence.get("effective_sample_size"),
            "mean_similarity": evidence.get("mean_similarity"),
            "success_distribution": evidence.get("success_distribution"),
            "major_failure_modes": evidence.get("major_failure_modes"),
        },
        "execution_plan": plan,
        "risk_flags": list(_pick_field(pick, "risk_flags", []) or []),
        "adaptive_policy": adaptive_policy,
        "adaptive_score": _pick_field(pick, "adaptive_score", meta.get("adaptive_score") or explain_context.get("adaptive_score") or adaptive_policy.get("adaptive_score")),
        "calibrated_probability": _pick_field(pick, "calibrated_probability", meta.get("calibrated_probability") or adaptive_policy.get("calibrated_probability")),
        "recommendation_strength": _pick_field(pick, "recommendation_strength", meta.get("recommendation_strength") or adaptive_policy.get("recommendation_strength")),
        "adaptive_action": _pick_field(pick, "adaptive_action", meta.get("adaptive_action") or adaptive_policy.get("action")),
        "feature_coverage": _pick_field(pick, "feature_coverage", meta.get("feature_coverage") or adaptive_policy.get("feature_coverage")),
        "expert_scores": dict(_pick_field(pick, "expert_scores", {}) or meta.get("expert_scores") or adaptive_policy.get("expert_scores") or {}),
        "expert_contributions": dict(_pick_field(pick, "expert_contributions", {}) or meta.get("expert_contributions") or adaptive_policy.get("expert_contributions") or {}),
        "missing_features": list(_pick_field(pick, "missing_features", []) or meta.get("missing_features") or adaptive_policy.get("missing_features") or []),
        "hard_block": bool(_pick_field(pick, "hard_block", False) or risk.get("hard_block") is True or meta.get("hard_block") is True or explain_context.get("hard_block") is True),
        "peer_candidates": peers,
        "decision_context_snapshot_id": _pick_field(pick, "decision_context_snapshot_id"),
    }


def _signal_thesis_context(pick: Any) -> Dict[str, Any]:
    signal = dict(_pick_field(pick, "signal", {}) or {})
    probability = dict(_pick_field(pick, "probability", {}) or {})
    risk = dict(_pick_field(pick, "risk", {}) or {})
    return {
        "initial_thesis": _pick_field(pick, "thesis", "") or _pick_field(pick, "why_selected", ""),
        "why_selected": _pick_field(pick, "why_selected", ""),
        "signal": signal,
        "signal_type": signal.get("signal_type") or _pick_field(pick, "champion_strategy") or _pick_field(pick, "strategy_id"),
        "probability_summary": {
            "up_probability_3d": probability.get("up_probability_3d"),
            "expected_return_3d": probability.get("expected_return_3d"),
            "uncertainty": probability.get("uncertainty"),
            "confidence": probability.get("confidence"),
        },
        "risk_summary": {
            "drawdown_probability": probability.get("drawdown_probability") or risk.get("drawdown_probability"),
            "risk_flags": risk.get("risk_flags") or _pick_field(pick, "risk_flags", []),
        },
    }


def _position_context(evidence: EvidencePack, extra_constraints: Dict[str, Any]) -> Dict[str, Any]:
    constraints = dict(getattr(evidence.frame, "constraints", {}) or {})
    constraints.update(extra_constraints or {})
    raw = str(constraints.get("position_context") or constraints.get("user_situation") or "").strip()
    quote = dict(constraints.get("user_quote") or extra_constraints.get("quote_snapshot") or {})
    return {
        "provided": bool(raw or quote),
        "raw": raw,
        "subject": getattr(evidence.frame, "subject", None),
        "numeric_values": _numeric_values(raw),
        "quote_snapshot": quote,
        "portfolio_slice": dict(evidence.portfolio_slice or {}),
        "plan_position": dict(extra_constraints.get("plan_position") or {}),
    }


def _user_context(evidence: EvidencePack) -> Dict[str, Any]:
    session = evidence.session
    frame = evidence.frame
    return {
        "session_id": session.session_id,
        "raw_message": frame.raw_message,
        "request": frame.request,
        "subject": frame.subject,
        "references": dict(frame.references or {}),
        "preferences": dict(session.user_preferences or {}),
        "focus_symbol": session.last_focus_symbol,
        "focus_rank": session.last_focus_rank,
        "active_run_id": session.active_run_id,
        "previous_run_id": session.previous_run_id,
    }


def build_decision_context_model(
    *,
    evidence: EvidencePack,
    run: Any = None,
    pick: Any = None,
    candidates: Iterable[Any] | None = None,
    objective: str | None = None,
    extra_constraints: Dict[str, Any] | None = None,
) -> DecisionContextModel:
    extra_constraints = dict(extra_constraints or {})
    resolved_objective = objective or objective_from_frame(evidence.frame)
    constraints = {
        **dict(getattr(evidence.frame, "constraints", {}) or {}),
        **extra_constraints,
        "freshness": getattr(evidence.frame, "freshness", None),
        "objective_source": "turn_frame",
    }
    return DecisionContextModel(
        market_context=_market_context(evidence, run),
        security_context=_security_context(pick, candidates),
        signal_thesis_context=_signal_thesis_context(pick),
        user_context=_user_context(evidence),
        position_context=_position_context(evidence, extra_constraints),
        objective=resolved_objective,
        constraints=constraints,
    )


def evaluate_thesis_lifecycle(context: DecisionContextModel) -> ThesisLifecycle:
    security = dict(context.security_context or {})
    thesis_ctx = dict(context.signal_thesis_context or {})
    probability = dict(security.get("probability") or {})
    risk = dict(security.get("risk") or {})
    position = dict(context.position_context or {})
    plan_position = dict(position.get("plan_position") or {})
    execution_state = str(security.get("execution_state") or "").upper()
    recommendation_state = str(security.get("recommendation_state") or "").upper()
    risk_flags = [str(item) for item in (security.get("risk_flags") or risk.get("risk_flags") or [])]
    adaptive_action = str(security.get("adaptive_action") or "").upper()
    recommendation_strength = str(security.get("recommendation_strength") or "").lower()
    delta: List[str] = []
    invalidations: List[str] = []

    up_prob = _safe_float(probability.get("up_probability_3d"), 0.0) or 0.0
    expected = _safe_float(probability.get("expected_return_3d"), 0.0) or 0.0
    confidence = _safe_float(probability.get("confidence"), 0.0) or 0.0
    uncertainty = _safe_float(probability.get("uncertainty"), 0.5) or 0.5
    drawdown = _safe_float(probability.get("drawdown_probability") or risk.get("drawdown_probability"), 0.5) or 0.5

    hard_risk_flags = [
        item
        for item in risk_flags
        if any(token in item.lower() for token in ("hard_block", "invalidated", "below_stop", "data_integrity"))
    ]
    if execution_state == "INVALIDATED" or recommendation_state == "INVALIDATED":
        invalidations.append("execution_state_invalidated")
    if bool(plan_position.get("below_stop")):
        invalidations.append("price_below_stop")
    if bool(security.get("hard_block")):
        invalidations.append("security_hard_block")
    if invalidations:
        state = "thesis_invalidated"
        delta.extend(invalidations)
    elif drawdown >= 0.45 or up_prob < 0.48 or expected < 0 or hard_risk_flags:
        state = "thesis_weakening"
        if drawdown >= 0.45:
            delta.append("drawdown_probability_high")
        if up_prob < 0.48:
            delta.append("win_probability_below_neutral")
        if expected < 0:
            delta.append("expected_return_negative")
        delta.extend(hard_risk_flags[:4])
    elif (
        (adaptive_action == "ENTRY" or up_prob >= 0.55)
        and expected > 0
        and confidence >= 0.35
        and uncertainty <= 0.25
        and (security.get("can_execute_now") or bool(plan_position.get("in_entry_zone")) or execution_state in {"PLAN_READY", "WAIT_PULLBACK"})
    ):
        state = "thesis_strengthened"
        delta.append("probability_and_execution_support_thesis")
    else:
        state = "thesis_unchanged"
        delta.append("no_material_change_against_initial_thesis")
    if risk_flags:
        delta.extend([f"risk_flag_observed:{item}" for item in risk_flags[:4]])
    if recommendation_strength in {"cautious", "exploratory"}:
        delta.append(f"adaptive_strength_{recommendation_strength}")

    initial = str(thesis_ctx.get("initial_thesis") or thesis_ctx.get("why_selected") or "").strip()
    current = {
        "thesis_strengthened": "当前证据增强了初始 thesis，但仍需要按执行条件处理。",
        "thesis_unchanged": "当前证据没有显著改变初始 thesis。",
        "thesis_weakening": "当前证据削弱了初始 thesis，需要降低动作强度。",
        "thesis_invalidated": "当前证据已经触发 thesis 失效条件。",
    }[state]
    return ThesisLifecycle(
        initial_thesis=initial,
        current_thesis_state=state,
        current_thesis=current,
        evidence_delta=delta[:8],
        invalidation_triggers=invalidations,
        risk_flags=risk_flags[:8],
    )


def _deterministic_action(context: DecisionContextModel, lifecycle: ThesisLifecycle) -> str:
    objective = str(context.objective or "")
    state = lifecycle.current_thesis_state
    security = dict(context.security_context or {})
    position = dict(context.position_context or {})
    if not security.get("symbol") and objective in {"evaluate_no_trade_decision", "open_or_add_position"}:
        return "NO_TRADE"
    has_position = bool(position.get("provided")) or objective == "manage_existing_position"
    can_execute = bool(security.get("can_execute_now"))
    adaptive_action = str(security.get("adaptive_action") or "").upper()
    if bool(security.get("hard_block")) and objective in {"evaluate_no_trade_decision", "open_or_add_position"}:
        return "NO_TRADE"
    if state == "thesis_invalidated":
        return "EXIT" if has_position else "NO_TRADE"
    if objective == "manage_existing_position":
        if state == "thesis_weakening":
            return "REDUCE"
        return "HOLD"
    if objective == "open_or_add_position":
        if adaptive_action == "ENTRY":
            return "ADD"
        if adaptive_action in {"WATCH", "WAIT"}:
            return "WAIT"
        if state == "thesis_strengthened" and can_execute:
            return "ADD"
        return "WAIT"
    if objective == "evaluate_no_trade_decision":
        if state == "thesis_invalidated" or bool(security.get("hard_block")):
            return "NO_TRADE"
        return "WAIT"
    return "WAIT"


def _risk_controls(context: DecisionContextModel, lifecycle: ThesisLifecycle) -> List[str]:
    security = dict(context.security_context or {})
    controls: List[str] = []
    stop_text = str(security.get("stop_text") or security.get("stop") or "").strip()
    entry_text = str(security.get("entry_text") or "").strip()
    take_text = str(security.get("take_text") or "").strip()
    if entry_text:
        controls.append(f"entry:{entry_text}")
    if stop_text:
        controls.append(f"stop_or_invalidation:{stop_text}")
    if take_text:
        controls.append(f"take_profit:{take_text}")
    controls.extend(str(item) for item in lifecycle.risk_flags[:3])
    return controls[:6]


def deterministic_synthesis(context: DecisionContextModel, lifecycle: ThesisLifecycle) -> DecisionSynthesis:
    action = _deterministic_action(context, lifecycle)
    confidence_seed = 0.35
    security = dict(context.security_context or {})
    probability = dict(security.get("probability") or {})
    if probability:
        confidence_seed = 0.4 * _clamp(probability.get("confidence"), default=0.5) + 0.3 * (1.0 - _clamp(probability.get("uncertainty"), default=0.5)) + 0.3
    rationale = {
        "HOLD": "thesis 未失效，当前更合理的是继续按原风控跟踪。",
        "ADD": "thesis 增强且执行条件支持，可以考虑按计划加/开仓。",
        "REDUCE": "thesis 正在削弱，先降低风险暴露。",
        "EXIT": "thesis 已失效，优先退出而不是等待修复。",
        "WAIT": "adaptive policy 仍保留候选，但当前动作强度以等待和跟踪为主。",
        "NO_TRADE": "缺少可决策标的、出现 hard block，或 thesis 已失效。",
    }[action]
    return DecisionSynthesis(
        action=action,
        confidence=max(0.0, min(1.0, confidence_seed)),
        rationale=rationale,
        thesis_state=lifecycle.current_thesis_state,
        risk_controls=_risk_controls(context, lifecycle),
        evidence_refs=[
            str(context.market_context.get("book_version") or ""),
            str(security.get("symbol") or ""),
            str(security.get("decision_context_snapshot_id") or ""),
        ],
        source="deterministic_policy",
        validator_result={"ok": True, "policy": "decision_action_schema"},
    )


def _llm_synthesis(context: DecisionContextModel, lifecycle: ThesisLifecycle) -> Dict[str, Any]:
    client = LLMClient()
    ok, reason = client.available()
    if not ok:
        return {"error": reason, "source": "llm_unavailable"}
    system = (
        "You are GP's Decision Synthesizer. You are not a stock picker and not a narrator. "
        "Use only the structured evidence. Return strict JSON with action, confidence, rationale, and risk_controls. "
        "Allowed actions: HOLD, ADD, REDUCE, EXIT, WAIT, NO_TRADE. Do not modify prices, probabilities, samples, ranks, or facts."
    )
    payload = {
        "decision_context_model": context.model_dump(),
        "thesis_lifecycle": lifecycle.model_dump(),
    }
    response = client.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.0,
        json_mode=True,
    )
    content = (((response or {}).get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
    obj = json.loads(content)
    return obj if isinstance(obj, dict) else {}


def validate_synthesis(raw: Dict[str, Any], fallback: DecisionSynthesis, lifecycle: ThesisLifecycle) -> DecisionSynthesis:
    action = str(raw.get("action") or fallback.action).upper()
    ok = action in ALLOWED_ACTIONS
    if not ok:
        action = fallback.action
    confidence = _clamp(raw.get("confidence"), default=fallback.confidence)
    rationale = str(raw.get("rationale") or fallback.rationale).strip()
    risk_controls = raw.get("risk_controls")
    if not isinstance(risk_controls, list):
        risk_controls = fallback.risk_controls
    source = fallback.source
    if raw:
        source = str(raw.get("source") or "llm_decision_synthesizer")
    return DecisionSynthesis(
        action=action,
        confidence=confidence,
        rationale=rationale,
        thesis_state=lifecycle.current_thesis_state,
        risk_controls=[str(item) for item in risk_controls][:6],
        evidence_refs=list(fallback.evidence_refs),
        source=source,
        validator_result={"ok": ok, "policy": "allowed_actions_only", "fallback_action": fallback.action},
    )


def synthesize_decision(
    *,
    evidence: EvidencePack,
    run: Any = None,
    pick: Any = None,
    candidates: Iterable[Any] | None = None,
    objective: str | None = None,
    extra_constraints: Dict[str, Any] | None = None,
    allow_llm: bool | None = None,
) -> Dict[str, Any]:
    context = build_decision_context_model(
        evidence=evidence,
        run=run,
        pick=pick,
        candidates=candidates,
        objective=objective,
        extra_constraints=extra_constraints,
    )
    lifecycle = evaluate_thesis_lifecycle(context)
    fallback = deterministic_synthesis(context, lifecycle)
    use_llm = bool(os.getenv("GP_DECISION_SYNTHESIS_LLM", "0") == "1") if allow_llm is None else bool(allow_llm)
    synthesis = fallback
    if use_llm:
        try:
            raw = _llm_synthesis(context, lifecycle)
            if raw and not raw.get("error"):
                synthesis = validate_synthesis(raw, fallback, lifecycle)
        except Exception as ex:  # noqa: BLE001
            synthesis = fallback.model_copy(update={"validator_result": {"ok": False, "error": f"{type(ex).__name__}: {ex}", "fallback_action": fallback.action}})
    return {
        "decision_context_model": context.model_dump(),
        "thesis_lifecycle": lifecycle.model_dump(),
        "decision_synthesis": synthesis.model_dump(),
        "decision_action": synthesis.action,
    }


def enrich_pick_with_synthesis(pick: CanonicalPick, synthesis: Dict[str, Any]) -> CanonicalPick:
    return pick.model_copy(
        update={
            "decision_context_model": dict(synthesis.get("decision_context_model") or {}),
            "thesis_lifecycle": dict(synthesis.get("thesis_lifecycle") or {}),
            "decision_synthesis": dict(synthesis.get("decision_synthesis") or {}),
            "decision_action": str(synthesis.get("decision_action") or "WAIT"),
        }
    )
