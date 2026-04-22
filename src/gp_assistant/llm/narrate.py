from __future__ import annotations

import json
from typing import Any, Dict

from .client import LLMClient
from ..core.errors import APIError


SYSTEM = """你是A股短线顾问系统的回答器。
"
"只能基于输入的 judgment 和 evidence 组织中文回答。
"
"不得编造新股票、新分数、新结论。
"
"优先给出结论、然后给出关键证据、再给出执行提醒。
"
"如果 tradeable=false 或 execution_state 不是 actionable，不要输出建仓肯定语气。"""


def render_reply(payload: Dict[str, Any]) -> str:
    client = LLMClient()
    ok, reason = client.available()
    if not ok:
        raise APIError(status_code=503, message='LLM unavailable for narration', detail={'reason': reason})
    messages = [
        {'role': 'system', 'content': SYSTEM},
        {'role': 'system', 'content': "当 payload.judgment.kind == 'chat' 时：不要输出任何交易结论/推荐/卖出判断，仅做轻量引导与礼貌回应。"},
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
    ]
    raw = client.chat(messages)
    content = (((raw or {}).get('choices') or [{}])[0].get('message') or {}).get('content')
    if not content:
        raise RuntimeError('LLM narrate returned empty content')
    return str(content).strip()
