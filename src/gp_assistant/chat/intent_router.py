from __future__ import annotations

"""
Deterministic intent router for chat orchestrator.

No LLM dependency. Uses keywords + simple slot resolution + session state.
"""

from typing import Dict, Any


def route_intent(message: str, session_state: Dict[str, Any]) -> Dict[str, Any]:
    s = (message or "").strip().lower()
    intent = "unknown"
    should_refresh = False
    target_kind = None

    # Refresh intents
    if any(k in s for k in ["刷新", "重新推荐", "今天最新", "最新推荐", "强制更新", "update", "refresh"]):
        intent = "refresh_recommendation"
        should_refresh = True
        return {"intent": intent, "should_refresh": should_refresh, "target_kind": target_kind}

    # Recommend / selection explain
    if any(k in s for k in ["今天给我", "来三只", "推荐", "现在适不适合", "空仓", "不交易的原因"]):
        if any(k in s for k in ["为什么", "原因", "解释", "rationale", "explain"]):
            intent = "selection_explain"
        elif any(k in s for k in ["空仓", "不交易", "不开仓"]):
            intent = "no_trade_reason"
        else:
            intent = "recommend"
        return {"intent": intent, "should_refresh": should_refresh, "target_kind": target_kind}

    # Pick detail / exit decision
    if any(k in s for k in ["止盈", "止损", "这只", "这票", "细节", "还能买吗", "还能不能买", "支撑", "阻力", "出不出", "第一只", "第二只", "第三只"]):
        intent = "pick_detail"
        target_kind = "symbol"
        return {"intent": intent, "should_refresh": should_refresh, "target_kind": target_kind}

    # Compare
    if any(k in s for k in ["对比", "比较", "哪个好", "选哪个"]):
        intent = "compare"
        target_kind = "symbols"
        return {"intent": intent, "should_refresh": should_refresh, "target_kind": target_kind}

    # Run diff
    if any(k in s for k in ["为什么不一样", "和上次", "变化", "变了", "不同"]):
        intent = "run_diff"
        return {"intent": intent, "should_refresh": should_refresh, "target_kind": target_kind}

    # Focus control
    if any(k in s for k in ["关注", "设为", "设置关注"]):
        intent = "set_focus"
        target_kind = "symbol"
        return {"intent": intent, "should_refresh": should_refresh, "target_kind": target_kind}

    return {"intent": intent, "should_refresh": should_refresh, "target_kind": target_kind}
