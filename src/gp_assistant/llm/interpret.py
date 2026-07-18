from __future__ import annotations

import json
import logging
from typing import Any, Dict

from .client import LLMClient
from ..contracts.objects import TurnFrame
from ..core.errors import IntentLLMUnavailable, IntentParseFailed, LLMPayloadBudgetExceeded
from ..runtime.utils import gen_id


LOGGER = logging.getLogger(__name__)


SYSTEM = """
你是 GP 股票助手的语义路由器。

只做一件事：把 user_message 结合 context 解析成严格 JSON 意图，不要给交易结论，不要输出解释文字。

输出必须是一个 JSON object，且只能包含这些顶层字段：
{
  "subject": "run|market|pick|symbol|compare_set|holding",
  "request": "term_explain|recommend|pick_detail|single_stock_query|live_entry_check|no_trade_explain|compare|exit_decision|run_change|chat",
  "freshness": "active_run|rebuild_run|next_session_plan",
  "references": {
    "symbol": "可选，6 位股票代码",
    "symbols": ["可选，多个 6 位股票代码"],
    "rank": "可选，候选排名数字",
    "focus_symbol": "可选，来自上下文的当前关注标的",
    "compare_symbols": ["可选，用于比较的多个代码"]
  },
  "constraints": {
    "topk": "可选，推荐数量，1 到 10",
    "require_refresh": "可选，是否要求刷新",
    "history_mode": "可选，用户是否明确要求上一轮/历史/此前结果",
    "term_text": "可选，term_explain 时要解释的术语或字段",
    "refresh_intent": "可选，none|current|live|rebuild",
    "allow_derived_data": true
  },
  "ambiguity": {
    "confidence": "0 到 1 的数字",
    "notes": ["简短说明判断依据"],
    "needs_clarification": false
  }
}

规则：
1. 先读 context.session、active_run、previous_run、recent_dialogue、candidate_summary 和 market，再判断 user_message。
2. 不要把追问误判成全新推荐；“继续 / 可以 / ？ / 这个怎么算 / 这是什么意思”通常是在追问最近业务结论。
3. 解释上一轮术语、计划字段、止盈止损、目标价来源、买入区来源、短确认续问时，使用 request="term_explain"。
4. 问某只标的逻辑、入选理由、止盈止损点、风控细节时，使用 request="pick_detail"，并尽量填 symbol 或 rank；如果只是问上一轮字段如何理解，则使用 term_explain。
5. 问现在能不能买、能不能冲、要不要等回踩、当前执行动作时，使用 live_entry_check；没有明确标的但在问市场是否可做时，使用 no_trade_explain。
6. 问该不该卖、减仓、止损、还能拿吗时，使用 exit_decision。
7. 问两个或多个标的谁更强、哪个好、为什么第二不是第一时，使用 compare。
8. 问这次和上次为什么不同、之前那只为什么没了时，使用 run_change。
9. 问推荐、机会、节后选择、给几只、榜单时，使用 recommend；非交易时段或下一交易窗口语境下 freshness 使用 next_session_plan。
10. 闲聊、问候、能力咨询使用 chat，不触发市场判断。
11. 不确定 symbol 或 rank 时不要编造；可以使用 context.session.last_focus_symbol 或 recent_dialogue 中明确的 focus。
12. 只输出 JSON，不要 Markdown，不要代码块，不要自然语言解释。
"""


SYSTEM += (
    '\nRule: if the user asks to analyze, check, or look at a concrete 6-digit A-share symbol, '
    'and it is not explicitly an exit/sell question or a comparison, use request="single_stock_query", '
    'subject="symbol", and put the 6-digit code in references.symbol.'
)
SYSTEM += (
    '\nRule: if the user gives intraday prices such as current price, day high, stable/sideways wording, '
    'and asks whether they can enter/buy now, use request="live_entry_check" and subject="symbol". '
    'Put any explicit 6-digit code in references.symbol; otherwise rely on the current focus symbol.'
)


def _short(value: Any, limit: int = 1200) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


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


def _extract_content(response: Dict[str, Any]) -> str:
    try:
        return str(((response or {}).get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
    except Exception:
        return ""


def _decode_turn_frame(content: str, user_message: str) -> TurnFrame:
    if not content:
        raise ValueError("LLM returned empty content")
    obj = json.loads(content)
    if not isinstance(obj, dict):
        raise ValueError("LLM returned JSON that is not an object")
    frame = _normalize_turn_obj(obj, user_message)
    if frame.request == "chat" and frame.freshness != "active_run":
        raise ValueError("LLM returned semantically inconsistent TurnFrame: chat intent must use freshness=active_run")
    return frame


def _repair_prompt(error: Exception, raw_output: str) -> str:
    return (
        "上一条输出不是合法或语义一致的 TurnFrame。"
        "请只重写为一个合法 JSON object，不要解释。"
        f"错误原因：{type(error).__name__}: {_short(error)}\n"
        f"上一条原始输出：{_short(raw_output)}"
    )


def parse_turn_frame(context: Dict[str, Any], user_message: str) -> TurnFrame:
    client = LLMClient()
    ok, reason = client.available()
    if not ok:
        LOGGER.warning(
            "intent_parse_unavailable",
            extra={
                "intent_request": None,
                "intent_subject": None,
                "retry_count": 0,
                "parse_error_type": "LLMUnavailable",
            },
        )
        raise IntentLLMUnavailable(reason)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps({"context": context, "user_message": user_message}, ensure_ascii=False)},
    ]
    first_content = ""
    try:
        first = client.chat(
            messages,
            json_mode=True,
            temperature=0.0,
            budget_stage="intent_routing",
        )
    except LLMPayloadBudgetExceeded:
        raise
    except Exception as provider_error:
        raise IntentLLMUnavailable(f"{type(provider_error).__name__}:{provider_error}") from provider_error
    first_content = _extract_content(first)
    try:
        frame = _decode_turn_frame(first_content, user_message)
        LOGGER.info(
            "intent_parse_success",
            extra={
                "intent_request": frame.request,
                "intent_subject": frame.subject,
                "retry_count": 0,
                "parse_error_type": None,
            },
        )
        return frame
    except Exception as first_error:
        LOGGER.warning(
            "intent_parse_retry",
            extra={
                "intent_request": None,
                "intent_subject": None,
                "retry_count": 1,
                "parse_error_type": type(first_error).__name__,
            },
        )
        repair_messages = [
            *messages,
            {"role": "assistant", "content": first_content},
            {"role": "user", "content": _repair_prompt(first_error, first_content)},
        ]
        second_content = ""
        try:
            second = client.chat(
                repair_messages,
                json_mode=True,
                temperature=0.0,
                budget_stage="intent_routing_repair",
            )
        except LLMPayloadBudgetExceeded:
            raise
        except Exception as provider_error:
            raise IntentLLMUnavailable(f"{type(provider_error).__name__}:{provider_error}") from provider_error
        second_content = _extract_content(second)
        try:
            frame = _decode_turn_frame(second_content, user_message)
            LOGGER.info(
                "intent_parse_success",
                extra={
                    "intent_request": frame.request,
                    "intent_subject": frame.subject,
                    "retry_count": 1,
                    "parse_error_type": None,
                },
            )
            return frame
        except Exception as second_error:
            raw_output = second_content or first_content
            LOGGER.error(
                "intent_parse_failed",
                extra={
                    "intent_request": None,
                    "intent_subject": None,
                    "retry_count": 1,
                    "parse_error_type": type(second_error).__name__,
                },
            )
            raise IntentParseFailed(
                "LLM intent parser returned invalid or inconsistent TurnFrame after retry",
                reason=f"{type(second_error).__name__}: {second_error}",
                raw_output=_short(raw_output),
                attempts=2,
            ) from second_error
