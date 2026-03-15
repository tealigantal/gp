# 简介：规则优先的意图识别，区分 recommend / followup_why / followup_tp / chat，
# 为对话编排提供轻量级槽位（如 topk）。
from __future__ import annotations

import re
from typing import Dict, Any


def detect_intent(text: str) -> Dict[str, Any]:
    """Rule-first intent detection with multi-turn follow-ups.

    Returns: {name: str, slots: dict}
    name in {general_chat, recommend, analyze_symbol, followup_why, followup_tp, ask_nth}
    """
    s = (text or "").strip()
    slots: dict[str, Any] = {}

    # recommend keywords
    if ("荐" in s) or ("latest" in s.lower()) or re.search(r"(荐股|买什么|推荐|建议|持仓|低吸|二买|服务荐股|服务推荐|最新推荐|今日推荐)", s):
        m = re.search(r"(\d+)只|topk\s*=?\s*(\d+)", s, re.IGNORECASE)
        if m:
            topk = int(m.group(1) or m.group(2))
            slots["topk"] = max(1, min(5, topk))
        return {"name": "recommend", "slots": slots}

    # ask for nth pick
    m2 = re.search(r"第\s*(\d+)\s*(只|个)", s)
    if m2:
        try:
            n = int(m2.group(1))
            if n >= 1:
                return {"name": "ask_nth", "slots": {"n": n}}
        except Exception:
            pass
    if re.search(r"(第一只|第一个|第1只|第1个|first)", s, re.IGNORECASE):
        return {"name": "ask_nth", "slots": {"n": 1}}
    if re.search(r"(第二只|第二个|第2只|第2个|second)", s, re.IGNORECASE):
        return {"name": "ask_nth", "slots": {"n": 2}}
    if re.search(r"(第三只|第三个|第3只|第3个|third)", s, re.IGNORECASE):
        return {"name": "ask_nth", "slots": {"n": 3}}

    # follow-up: why / reasoning
    if re.search(r"(为什么|理由|原因)", s):
        return {"name": "followup_why", "slots": {}}

    # follow-up: trade points / SL/TP / support-resistance / timing
    if re.search(r"(买卖点|止损|止盈|支撑|阻力|入手时机|买点|卖点)", s):
        return {"name": "followup_tp", "slots": {}}

    # analyze symbol / kline
    if re.search(r"(研究|看看|看下|看一下).*?(K线|日线)|K线|日线", s):
        return {"name": "analyze_symbol", "slots": {}}

    return {"name": "general_chat", "slots": {}}
