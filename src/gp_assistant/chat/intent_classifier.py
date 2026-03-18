from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from ..llm.client import LLMClient
from .intent_schema import IntentClassification
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

