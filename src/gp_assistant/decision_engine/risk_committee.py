from __future__ import annotations

import json
from typing import Any, Dict, List

from ..llm.client import LLMClient


DECISION_ORDER = {"no_trade": 0, "observe": 1, "recommend": 2}


def _downgrade(left: str, right: str) -> str:
    left_key = left if left in DECISION_ORDER else "no_trade"
    right_key = right if right in DECISION_ORDER else "no_trade"
    return left_key if DECISION_ORDER[left_key] <= DECISION_ORDER[right_key] else right_key


def mathematical_decision(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    ranked = list(candidates)
    top = ranked[0] if ranked else None
    if top is None:
        return {"decision": "no_trade", "selected_symbols": [], "reason": "no_candidates"}
    prob = top.get("probability") or {}
    evidence = (prob.get("evidence") or {})
    risk = top.get("risk") or {}
    eff_n = float(evidence.get("effective_sample_size") or 0.0)
    drawdown = float(risk.get("drawdown_probability") or prob.get("drawdown_probability") or 1.0)
    if eff_n < 10:
        return {"decision": "no_trade", "selected_symbols": [], "reason": "effective_sample_too_small"}
    if eff_n < 30:
        return {"decision": "observe", "selected_symbols": [top["symbol"]], "reason": "effective_sample_low"}
    if (
        float(prob.get("up_probability_3d") or 0.0) >= 0.55
        and float(prob.get("expected_return_3d") or 0.0) > 0.0
        and drawdown < 0.45
        and float(top.get("ranking", {}).get("ranking_score") or 0.0) > 0.0
    ):
        return {"decision": "recommend", "selected_symbols": [top["symbol"]], "reason": "math_rank_supports_top_candidate"}
    return {"decision": "observe", "selected_symbols": [top["symbol"]], "reason": "math_edge_not_strong_enough"}


def _llm_risk_committee(input_context: Dict[str, Any]) -> Dict[str, Any]:
    client = LLMClient()
    ok, reason = client.available()
    if not ok:
        return {
            "decision": input_context.get("math_decision", {}).get("decision", "no_trade"),
            "selected_symbols": list(input_context.get("math_decision", {}).get("selected_symbols") or []),
            "reason": f"risk_committee_llm_unavailable:{reason}",
            "source": "deterministic_policy",
            "llm_available": False,
        }
    system = (
        "You are GP's risk committee, not a portfolio manager. "
        "Return strict JSON only. You may downgrade/reject the math-ranked decision, "
        "but you may not promote any candidate outside math ranking or invent facts. "
        "Allowed decision values: recommend, observe, no_trade."
    )
    response = client.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(input_context, ensure_ascii=False)},
        ],
        temperature=0.0,
        json_mode=True,
    )
    content = (((response or {}).get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
    obj = json.loads(content)
    if not isinstance(obj, dict):
        raise ValueError("risk committee response must be JSON object")
    obj.setdefault("source", "llm_risk_committee")
    obj.setdefault("llm_available", True)
    return obj


def validate_committee_decision(
    *,
    llm_decision: Dict[str, Any],
    math_decision: Dict[str, Any],
    ranked_candidates: List[Dict[str, Any]],
) -> Dict[str, Any]:
    math_rank_symbols = [str(item.get("symbol")) for item in ranked_candidates if item.get("symbol")]
    math_selected = [str(symbol) for symbol in (math_decision.get("selected_symbols") or []) if str(symbol)]
    allowed_symbols = set(math_rank_symbols[: max(1, len(math_selected) or 1)])
    decision = str(llm_decision.get("decision") or math_decision.get("decision") or "no_trade")
    if decision not in DECISION_ORDER:
        decision = "no_trade"
    decision = _downgrade(decision, str(math_decision.get("decision") or "no_trade"))
    selected = [str(symbol) for symbol in (llm_decision.get("selected_symbols") or math_selected) if str(symbol)]
    invalid_symbols = [symbol for symbol in selected if symbol not in allowed_symbols]
    if invalid_symbols:
        selected = [symbol for symbol in selected if symbol in allowed_symbols]
        decision = _downgrade(decision, "observe")
    if decision == "recommend" and not selected:
        decision = "observe"
    if decision == "no_trade":
        selected = []
    return {
        "ok": not invalid_symbols,
        "final_decision": decision,
        "selected_symbols": selected,
        "invalid_symbols": invalid_symbols,
        "math_decision": math_decision,
        "llm_decision": llm_decision,
        "policy": "llm_can_only_downgrade_math_ranking",
    }


def run_risk_committee(input_context: Dict[str, Any], ranked_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    math = mathematical_decision(ranked_candidates)
    enriched = {**input_context, "math_decision": math}
    try:
        llm_decision = _llm_risk_committee(enriched)
    except Exception as ex:  # noqa: BLE001
        llm_decision = {
            "decision": math.get("decision", "no_trade"),
            "selected_symbols": list(math.get("selected_symbols") or []),
            "reason": f"risk_committee_failed:{type(ex).__name__}",
            "source": "deterministic_policy",
            "llm_available": False,
        }
    return validate_committee_decision(
        llm_decision=llm_decision,
        math_decision=math,
        ranked_candidates=ranked_candidates,
    )


def render_narrative_from_validated_decision(snapshot: Dict[str, Any]) -> str:
    decision = str(snapshot.get("final_decision") or "no_trade")
    selected = list(snapshot.get("selected_symbols") or [])
    candidates = list(snapshot.get("candidate_list") or [])
    top = next((item for item in candidates if item.get("symbol") in selected), candidates[0] if candidates else None)
    if top is None:
        return "当前没有足够相似历史样本和风险收益证据，先不推荐。"
    prob = top.get("probability") or {}
    evidence = prob.get("evidence") or {}
    risk = top.get("risk") or {}
    if decision == "recommend":
        return (
            f"{top.get('symbol')} 当前进入推荐：相似历史案例 {evidence.get('sample_size', 0)} 个，"
            f"有效样本 {float(evidence.get('effective_sample_size') or 0.0):.1f}，"
            f"3日上涨概率 {float(prob.get('up_probability_3d') or 0.0) * 100:.1f}%，"
            f"期望收益 {float(prob.get('expected_return_3d') or 0.0) * 100:.2f}%，"
            f"回撤概率 {float(risk.get('drawdown_probability') or prob.get('drawdown_probability') or 0.0) * 100:.1f}%。"
        )
    if decision == "observe":
        return (
            f"{top.get('symbol')} 有结构但只观察：相似样本或风险收益证据还不够强，"
            f"不确定性 {float(prob.get('uncertainty') or 0.0):.2f}，"
            f"主要风险 {', '.join(risk.get('risk_flags') or ['evidence_not_strong_enough'])}。"
        )
    return "当前不推荐交易：候选的相似历史证据、概率优势或风险调整后收益不足。"
