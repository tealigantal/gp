from __future__ import annotations

import json
from typing import Any, Dict

from .client import LLMClient
from ..contracts.objects import TurnFrame
from ..runtime.utils import gen_id


SYSTEM = """
你是 GP 股票助手的语义路由器。

只做一件事：把 user_message 结合 context 解析成严格 JSON 意图，不要给交易结论。

必须输出字段：
- subject: run | market | pick | symbol | compare_set | holding
- request: recommend | pick_detail | live_entry_check | no_trade_explain | compare | exit_decision | run_change | chat
- freshness: active_run | latest_5m | rebuild_run | next_session_plan
- references:
  - symbol?: string
  - symbols?: string[]
  - rank?: number
  - focus_symbol?: string
  - compare_symbols?: string[]
- constraints:
  - topk?: number
  - require_refresh?: boolean
  - allow_derived_data?: boolean
- ambiguity:
  - confidence: number
  - notes: string[]
  - needs_clarification: boolean

规则：
1. 先理解上下文里的 active_run、previous_run、focus_symbol、最近对话，再理解用户句子。
2. 不要把 follow-up 误判成全新推荐。
3. “现在还能买吗 / 还能冲吗 / 要不要等回踩 / 先别碰”这类强调当前执行状态的，优先 live_entry_check 或 no_trade_explain。
4. “止盈止损点 / 这只逻辑 / 第二只为什么”优先 pick_detail。
5. “该不该卖 / 减仓 / 止损 / 还能拿吗”优先 exit_decision。
6. “为什么这次和上次不一样 / 之前那只怎么没了”优先 run_change。
7. 非交易时段 ask top N 时，freshness 优先 next_session_plan，不要因为不能立刻开仓就拒绝推荐。
8. 允许模糊，但不要编造 symbol 或 rank；不确定时降低 confidence，并标 needs_clarification。
9. 只输出 JSON，不要有 Markdown 或解释。
"""


def _fallback_chat_frame(user_message: str, reason: str) -> TurnFrame:
    return TurnFrame.model_validate(
        {
            "frame_id": gen_id("frame"),
            "raw_message": user_message,
            "subject": "market",
            "request": "chat",
            "freshness": "active_run",
            "references": {},
            "constraints": {"allow_derived_data": True},
            "ambiguity": {
                "confidence": 0.25,
                "notes": [f"llm unavailable for concern parsing: {reason}"],
                "needs_clarification": False,
            },
        }
    )


def _normalize_turn_obj(obj: Dict[str, Any], user_message: str) -> TurnFrame:
    refs = obj.get("references", {})
    if not isinstance(refs, dict):
        refs = {}
    constraints = obj.get("constraints", {})
    if not isinstance(constraints, dict):
        constraints = {}
    if "allow_derived_data" not in constraints:
        constraints["allow_derived_data"] = True
    ambiguity = obj.get("ambiguity", {})
    if not isinstance(ambiguity, dict):
        ambiguity = {}
    try:
        confidence = float(ambiguity.get("confidence", 0.5))
    except Exception:
        confidence = 0.5
    ambiguity["confidence"] = max(0.0, min(1.0, confidence))
    notes = ambiguity.get("notes")
    ambiguity["notes"] = [str(item) for item in notes] if isinstance(notes, list) else []
    ambiguity["needs_clarification"] = bool(ambiguity.get("needs_clarification", False))
    obj["references"] = refs
    obj["constraints"] = constraints
    obj["ambiguity"] = ambiguity
    obj["frame_id"] = gen_id("frame")
    obj["raw_message"] = user_message
    return TurnFrame.model_validate(obj)


def parse_turn_frame(context: Dict[str, Any], user_message: str) -> TurnFrame:
    client = LLMClient()
    ok, reason = client.available()
    if not ok:
        return _fallback_chat_frame(user_message, reason)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps({"context": context, "user_message": user_message}, ensure_ascii=False)},
    ]
    raw = client.chat(messages, json_mode=True)
    content = (((raw or {}).get("choices") or [{}])[0].get("message") or {}).get("content")
    if not content:
        raise RuntimeError("LLM interpret returned empty content")
    obj = json.loads(content)
    return _normalize_turn_obj(obj, user_message)
