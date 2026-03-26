from __future__ import annotations

import json
from typing import Any, Dict

from .client import LLMClient
from ..contracts.objects import TurnFrame
from ..core.errors import APIError
from ..runtime.utils import gen_id


SYSTEM = """
你是对话荐股系统的语义解释器。
仅输出一个严格 JSON 对象，不得包含多余文字、说明、Markdown 或代码块。

必须字段：subject, request, freshness, references, constraints, ambiguity。

取值约束：
- subject ∈ { "run", "pick", "symbol", "compare_set", "holding", "market" }
- request ∈ { "recommend", "explain", "live_check", "compare", "exit", "run_change" }
- freshness ∈ { "current_book", "latest_5m", "rebuild_daybook" }
- references: 必须是“对象”，允许键：
  - symbol: string
  - symbols: string[]
  - compare_symbols: string[]
  - focus_symbol: string
  - rank: number
- constraints: 对象（可为空 {}），例如 { "topk": 3 }。
- ambiguity: 对象，且包含 { "confidence": number(0~1), "notes": string[] }。

输出示例（仅示例，不要照抄数值）：
{"subject":"run","request":"recommend","freshness":"current_book","references":{},"constraints":{},"ambiguity":{"confidence":0.8,"notes":[]}}
"""


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

    # Defaults
    obj.setdefault('subject', 'run')
    obj.setdefault('request', 'recommend')
    obj.setdefault('freshness', 'current_book')

    # Normalize references/constraints/ambiguity to satisfy schema
    allow_ref_keys = {'symbol', 'symbols', 'compare_symbols', 'focus_symbol', 'rank'}
    refs = obj.get('references', {})
    if not isinstance(refs, dict):
        merged: Dict[str, Any] = {}
        if isinstance(refs, list):
            for it in refs:
                if isinstance(it, dict):
                    for k, v in it.items():
                        if k in allow_ref_keys and k not in merged:
                            merged[k] = v
        refs = merged if merged else {}
    # Coerce common shapes
    try:
        sym_list = refs.get('symbols')
        if isinstance(sym_list, str):
            refs['symbols'] = [s.strip() for s in [sym_list] if s and isinstance(s, str)]
    except Exception:
        pass
    try:
        rk = refs.get('rank')
        if isinstance(rk, str) and rk.isdigit():
            refs['rank'] = int(rk)
    except Exception:
        pass
    obj['references'] = refs if isinstance(refs, dict) else {}

    cons = obj.get('constraints', {})
    obj['constraints'] = cons if isinstance(cons, dict) else {}

    amb = obj.get('ambiguity', {'confidence': 0.5, 'notes': []})
    if not isinstance(amb, dict):
        amb = {'confidence': 0.5, 'notes': []}
    try:
        c = float(amb.get('confidence'))
        if c < 0:
            c = 0.0
        if c > 1:
            c = 1.0
        amb['confidence'] = c
    except Exception:
        amb['confidence'] = 0.5
    try:
        notes = amb.get('notes')
        amb['notes'] = [str(x) for x in notes] if isinstance(notes, list) else []
    except Exception:
        amb['notes'] = []
    obj['ambiguity'] = amb

    obj['frame_id'] = gen_id('frame')
    obj['raw_message'] = user_message
    return TurnFrame.model_validate(obj)

