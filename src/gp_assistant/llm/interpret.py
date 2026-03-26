from __future__ import annotations

import json
from typing import Any, Dict

from .client import LLMClient
from ..contracts.objects import TurnFrame
from ..core.errors import APIError
from ..runtime.utils import gen_id


SYSTEM = """你是对话荐股系统的语义解释器。
"
"你的唯一任务，是把用户当前这句话连同上下文，解析成结构化 JSON。
"
"不要输出解释文本，不要输出 markdown。
"
"字段要求：subject, request, freshness, references, constraints, ambiguity。
"
"subject 只能是 run|pick|symbol|compare_set|holding|market。
"
"request 只能是 recommend|explain|live_check|compare|exit|run_change。
"
"freshness 只能是 current_book|latest_5m|rebuild_daybook。
"
"ambiguity 必须包含 confidence(0-1) 与 notes。"""


def parse_turn_frame(context: Dict[str, Any], user_message: str) -> TurnFrame:
    client = LLMClient()
    ok, reason = client.available()
    if not ok:
        raise APIError(status_code=503, message='LLM unavailable for concern parsing', detail={'reason': reason})
    messages = [
        {'role': 'system', 'content': SYSTEM},
        {'role': 'user', 'content': json.dumps({'context': context, 'user_message': user_message}, ensure_ascii=False)},
    ]
    raw = client.chat(messages, json_mode=True)
    content = (((raw or {}).get('choices') or [{}])[0].get('message') or {}).get('content')
    if not content:
        raise RuntimeError('LLM interpret returned empty content')
    obj = json.loads(content)
    obj.setdefault('subject', 'run')
    obj.setdefault('request', 'recommend')
    obj.setdefault('freshness', 'current_book')
    obj.setdefault('references', {})
    obj.setdefault('constraints', {})
    obj.setdefault('ambiguity', {'confidence': 0.5, 'notes': []})
    obj['frame_id'] = gen_id('frame')
    obj['raw_message'] = user_message
    return TurnFrame.model_validate(obj)
