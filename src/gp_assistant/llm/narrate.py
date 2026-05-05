from __future__ import annotations

import json
from typing import Any, Dict

from .client import LLMClient
from ..core.errors import APIError


SYSTEM = """
你是 A 股短线股票助手的中文解释器。

要求：
1. 只能基于 payload 里的结构化事实作答，不得编造价格、买点、止损、止盈或不存在的数据状态。
2. 先说结论，再说关键依据，再说执行提醒。
3. 非交易时段要明确这是“下一交易窗口计划”，不要说系统不可用、只读、slot unavailable。
4. 如果当前不是 BUY_NOW，不要用强推口吻。
5. 不要输出任何 JSON，只输出自然中文。
"""


def render_reply(payload: Dict[str, Any]) -> str:
    client = LLMClient()
    ok, reason = client.available()
    if not ok:
        raise APIError(status_code=503, message="LLM unavailable for narration", detail={"reason": reason})
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    raw = client.chat(messages)
    content = (((raw or {}).get("choices") or [{}])[0].get("message") or {}).get("content")
    if not content:
        raise RuntimeError("LLM narrate returned empty content")
    return str(content).strip()
