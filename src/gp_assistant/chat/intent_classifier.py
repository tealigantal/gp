from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from ..llm.client import LLMClient
from .intent_schema import IntentClassification, PlannerPlan
from . import session_store as store


def _truthy(v: str | None) -> bool:
    if v is None:
        return False
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _session_min_context(session_id: str) -> Dict[str, Any]:
    st = store.get_state(session_id)
    ctx = {
        "active_run_id": st.get("active_run_id"),
        "active_symbols": st.get("active_symbols") or [],
        "focus_symbol": st.get("focused_symbol") or st.get("current_focus_symbol"),
    }
    # include last recommend light summary when available
    try:
        last = store.load_last_recommend(session_id)
        if last:
            ctx["last_as_of"] = last.get("as_of")
            ctx["top_symbols"] = [
                str((p or {}).get("symbol") or "")
                for p in (last.get("picks") or [])[:3]
                if isinstance(p, dict)
            ]
            ctx["tradeable"] = last.get("tradeable")
            ctx["reason"] = last.get("reason")
    except Exception:
        pass
    return ctx


def _build_messages(user: str, ctx: Dict[str, Any]) -> List[Dict[str, str]]:
    sys_rules = (
        "你是一个意图分类器，不是交易顾问。\n"
        "严格输出 JSON，对象字段如下：{intent, symbol, symbols, ordinal, query_rewrite, confidence, reason}。\n"
        "只做：意图分类 和 槽位抽取。禁止给出买卖/减仓/止损/止盈/入场/空仓建议。\n"
        "intent 仅限：recommend | ask_no_trade_reason | ranking_explain | compare_symbols | analyze_symbol | exit_decision | refresh_recommend | general_explain | unknown。\n"
        "slot 规则：\n"
        "- symbol：尽量抽取单一标的（6位代码或名称），如‘这只/它/这个’映射 focus_symbol。\n"
        "- symbols：比较/集合场景抽取多标的。\n"
        "- ordinal：解析第一只/第二只/前两只/第三个等。\n"
        "- query_rewrite：将自然语言改写成结构化表达。\n"
        "- confidence：0~1，小数。\n"
        "- reason：一句话分类理由。\n"
        "如果无法可靠分类，intent=unknown，confidence<=0.5。\n"
    )
    context_hint = (
        f"会话上下文：active_run_id={ctx.get('active_run_id')}, focus_symbol={ctx.get('focus_symbol')}, "
        f"active_symbols={ctx.get('active_symbols')}, top_symbols={ctx.get('top_symbols')}。"
    )
    return [
        {"role": "system", "content": sys_rules},
        {"role": "system", "content": context_hint},
        {"role": "user", "content": user},
    ]


def _safe_parse_json(s: str) -> Dict[str, Any]:
    try:
        return json.loads(s)
    except Exception:
        # try extract first {...}
        try:
            start = s.find("{")
            end = s.rfind("}")
            if start >= 0 and end > start:
                return json.loads(s[start : end + 1])
        except Exception:
            pass
    return {}


def classify_intent_llm(session_id: str, message: str) -> IntentClassification:
    # Reuse the existing unified LLMClient
    client = LLMClient()
    ctx = _session_min_context(session_id)
    msgs = _build_messages(message, ctx)
    resp = client.chat(msgs, temperature=0.0, json_mode=True)
    content = (
        (resp.get("choices", [{}])[0].get("message", {}) or {}).get("content")
        if isinstance(resp, dict)
        else None
    )
    obj = _safe_parse_json(str(content or "")) if content else {}
    ic = IntentClassification.from_dict(obj)
    return ic


# ---------------- Planner v2 ----------------

def _planner_messages(user: str, ctx: Dict[str, Any]) -> List[Dict[str, str]]:
    sys_rules = (
        "你是交易聊天的 Planner。\n"
        "只输出严格 JSON，不要解释。字段：{intent, symbol, symbols, ordinal, topk, force_refresh, reuse_active_run, response_card_kind, focus_symbol, compare_symbols, explanation_target, confidence, reason}。\n"
        "规则：\n"
        "- intent 仅限：recommend_topn | explain_no_trade | analyze_symbol | analyze_nth_pick | compare_symbols | exit_decision | explain_ranking | explain_run_change | risk_points | clarify_tradeability | refresh_recommend | general_explain | unknown。\n"
        "- 不要编造价格/止损/止盈/RR/可交易状态，Planner 不产出交易数值。\n"
        "- 若用户含糊其辞，优先绑定当前会话 active_run 与 focus_symbol。\n"
        "- 判定是否复用 active run：默认 reuse_active_run=true；用户要求刷新或 run 过期时 force_refresh=true。\n"
        "- topk 缺省值3；ordinal 支持第一只/第二只/第三只。\n"
        "- response_card_kind 建议值：recommendation | no_trade | pick_detail | compare | exit_decision | run_change | status | text。\n"
        "- 置信度 confidence 0~1。\n"
    )
    context_hint = (
        f"会话上下文：active_run_id={ctx.get('active_run_id')}, previous_run_id={ctx.get('previous_run_id')}, "
        f"focus_symbol={ctx.get('focus_symbol')}, active_symbols={ctx.get('active_symbols')}。"
    )
    return [
        {"role": "system", "content": sys_rules},
        {"role": "system", "content": context_hint},
        {"role": "user", "content": user},
    ]


def plan_message(session_id: str, message: str) -> PlannerPlan:
    """LLM-first planner with strict JSON output. Falls back to rules when unavailable/invalid."""
    # Try LLM when enabled; else direct fallback
    use_llm = _truthy(os.getenv("GP_ENABLE_LLM_INTENT", "1"))
    ctx = _session_min_context(session_id)
    client = LLMClient()
    obj: Dict[str, Any] = {}
    if use_llm:
        try:
            msgs = _planner_messages(message, ctx)
            resp = client.chat(msgs, temperature=0.0, json_mode=True)
            content = (
                (resp.get("choices", [{}])[0].get("message", {}) or {}).get("content")
                if isinstance(resp, dict)
                else None
            )
            obj = _safe_parse_json(str(content or "")) if content else {}
        except Exception:
            obj = {}
    plan = PlannerPlan.from_dict(obj)
    # schema validity guard
    if not plan.intent or plan.intent == "unknown" or (plan.confidence or 0.0) < float(os.getenv("GP_INTENT_CONFIDENCE", "0.6")):
        # Rule fallback to keep system functional
        from .intent import detect_intent as _detect

        intent = _detect_intent_from_rules(_detect, session_id, message)
        return intent
    return plan


def _detect_intent_from_rules(detect, session_id: str, message: str) -> PlannerPlan:  # noqa: ANN001
    """Translate legacy detect_intent result into PlannerPlan with reasonable defaults."""
    res = detect(message)
    name = str((res or {}).get("name") or "unknown")
    slots = (res or {}).get("slots") or {}
    plan = PlannerPlan(intent="unknown", confidence=0.5, reason="rule_fallback")
    # map names
    if name == "recommend":
        plan.intent = "recommend_topn"
        plan.topk = int(slots.get("topk", 3))
        plan.response_card_kind = "recommendation"
    elif name == "ask_no_trade_reason":
        plan.intent = "explain_no_trade"
        plan.response_card_kind = "no_trade"
    elif name == "ranking_explain":
        plan.intent = "explain_ranking"
        plan.response_card_kind = "pick_detail"
    elif name == "compare_symbols":
        plan.intent = "compare_symbols"
        syms = slots.get("symbols") or []
        plan.compare_symbols = [str(s) for s in syms if str(s)]
        plan.response_card_kind = "compare"
    elif name == "analyze_symbol":
        plan.intent = "analyze_symbol"
        plan.symbol = str(slots.get("symbol") or "") or None
        plan.response_card_kind = "pick_detail"
    elif name == "exit_decision":
        plan.intent = "exit_decision"
        plan.response_card_kind = "exit_decision"
    elif name == "refresh_trade_plan" or name == "refresh_recommend":
        plan.intent = "refresh_recommend"
        plan.force_refresh = True
        plan.response_card_kind = "status"
    else:
        plan.intent = "general_explain"
        plan.response_card_kind = "text"
    # contextual defaults
    st = store.get_state(session_id)
    if plan.intent in {"analyze_symbol", "exit_decision"} and not plan.symbol:
        # use focus or ordinal resolution
        plan.symbol = (st.get("focused_symbol") or st.get("current_focus_symbol"))
    if plan.intent == "analyze_nth_pick" and not plan.ordinal:
        plan.ordinal = 1
    plan.reuse_active_run = True
    return plan

