# 简介：规则优先的意图识别，区分 recommend / followup_why / followup_tp / chat，
# 为对话编排提供轻量级槽位（如 topk）。
from __future__ import annotations

import re
from typing import Dict, Any


def detect_intent(text: str) -> Dict[str, Any]:
    """Rule-first intent detection.

    Returns: {name: str, slots: dict}
    name in {chat, recommend, followup_why, followup_tp}
    """
    s = (text or "").strip()
    slots: dict[str, Any] = {}
    # recommend keywords
    if re.search(r"(荐股|买什么|推荐|建议|持仓|低吸|二买)", s):
        # extract topk if user mentions just a digit
        m = re.search(r"(\d+)只|topk\s*=?\s*(\d+)", s, re.IGNORECASE)
        if m:
            topk = int(m.group(1) or m.group(2))
            slots["topk"] = max(1, min(5, topk))
        return {"name": "recommend", "slots": slots}
    if re.search(r"(为什么|理由|原因)", s):
        return {"name": "followup_why", "slots": {}}
    if re.search(r"(买卖点|止损|支撑|阻力|入手时机)", s):
        return {"name": "followup_tp", "slots": {}}
    return {"name": "chat", "slots": {}}
