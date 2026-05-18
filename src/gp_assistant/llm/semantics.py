from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .client import LLMClient


@dataclass
class CardExplanationQuality:
    is_explaining_card: bool = False
    grounded_to_card: bool = False
    needs_repair: bool = True
    reason: Optional[str] = None


@dataclass
class SemanticTurnSignals:
    history_mode: bool = False
    refresh_intent: str = "none"
    term_text: Optional[str] = None
    card_explanation_quality: CardExplanationQuality = field(default_factory=CardExplanationQuality)


@dataclass
class AnnouncementRiskAssessment:
    risk_level: Optional[str] = None
    evidence: List[str] = field(default_factory=list)
    reason: Optional[str] = None


def _extract_content(response: Dict[str, Any]) -> str:
    try:
        return str(((response or {}).get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
    except Exception:
        return ""


def _short(value: Any, limit: int = 1200) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def _json_chat(
    *,
    system: str,
    payload: Dict[str, Any],
    client: LLMClient | None = None,
    repair_label: str = "semantic_json",
) -> Dict[str, Any]:
    client = client or LLMClient()
    ok, reason = client.available()
    if not ok:
        raise RuntimeError(f"LLM semantic layer unavailable: {reason}")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    first_content = ""
    try:
        first = client.chat(messages, json_mode=True, temperature=0.0)
        first_content = _extract_content(first)
        parsed = json.loads(first_content)
        if not isinstance(parsed, dict):
            raise ValueError("semantic result must be a JSON object")
        return parsed
    except Exception as first_error:
        repair_messages = [
            *messages,
            {"role": "assistant", "content": first_content},
            {
                "role": "user",
                "content": (
                    f"上一条 {repair_label} 输出不是合法 JSON object。"
                    f"请只重写为合法 JSON object，不要解释。错误：{type(first_error).__name__}: {_short(first_error)}"
                ),
            },
        ]
        second = client.chat(repair_messages, json_mode=True, temperature=0.0)
        second_content = _extract_content(second)
        parsed = json.loads(second_content)
        if not isinstance(parsed, dict):
            raise ValueError("semantic repair result must be a JSON object")
        return parsed


TURN_SEMANTIC_SYSTEM = """
你是 GP 股票助手的语义信号分类器。只输出 JSON，不输出解释。

根据 user_message、可选 TurnFrame、session 和 book，判断这些内部信号：
{
  "history_mode": true|false,
  "refresh_intent": "none|current|live|rebuild",
  "term_text": "如果用户在问术语或上一轮字段含义，填要解释的术语；否则 null"
}

要求：
1. 不要用关键词匹配方式解释你的判断；按整句话语义和上下文判断。
2. refresh_intent=live 表示用户需要当前/盘中/执行状态；rebuild 表示要重新生成推荐或新计划。
3. history_mode=true 表示用户明确要求上一轮、历史、此前结果或本轮对比上一轮。
4. 只返回上述字段。
"""


def analyze_turn_semantics(
    *,
    user_message: str,
    session: Dict[str, Any] | None = None,
    book: Dict[str, Any] | None = None,
    frame: Dict[str, Any] | None = None,
    client: LLMClient | None = None,
) -> SemanticTurnSignals:
    obj = _json_chat(
        system=TURN_SEMANTIC_SYSTEM,
        payload={
            "user_message": user_message,
            "session": session or {},
            "book": book or {},
            "frame": frame or {},
        },
        client=client,
        repair_label="turn_semantics",
    )
    refresh = str(obj.get("refresh_intent") or "none").strip().lower()
    if refresh not in {"none", "current", "live", "rebuild"}:
        refresh = "none"
    term = obj.get("term_text")
    term_text = str(term).strip() if term is not None and str(term).strip() else None
    return SemanticTurnSignals(
        history_mode=bool(obj.get("history_mode", False)),
        refresh_intent=refresh,
        term_text=term_text,
    )


CARD_QUALITY_SYSTEM = """
你是 GP 股票助手的卡片解释质量评审器。只输出 JSON，不输出解释。

判断 assistant_text 是否是在解释 card_message 中的业务卡片信息，而不是只复述标题或说空话。
输出：
{
  "is_explaining_card": true|false,
  "grounded_to_card": true|false,
  "needs_repair": true|false,
  "reason": "简短原因"
}

标准：
1. grounded_to_card=true 表示文本明确关联了卡片中的至少一个事实、标的、状态、动作、排序、风险或缺失数据。
2. is_explaining_card=true 表示文本说明了这些事实对结论或下一步的含义。
3. 如果文本为空、等于 fallback_text、泄露内部工具/模块/trace、或和卡片无关，needs_repair=true。
4. 不按固定关键词判断，按语义判断。
"""
CARD_QUALITY_SYSTEM += """

Parameter-quality standards:
1. If card_message contains entry/trigger/stop/take/RR/VWAP/volume/RS fields,
   assistant_text must explain parameter meaning, current value, threshold or
   expected condition, pass/fail state, and effect on entry.
2. Relevant fields include entry_low-entry_high, trigger_price, stop_price,
   take1/take2, rr_to_take1, slot_rel_vol, rs_index, rs_industry,
   price_vs_vwap, and vwap.
3. RS means relative strength comparison, not RSI.
4. Mark needs_repair=true if assistant_text only says "volume and RS confirm",
   "wait for confirmation", "enter after conditions are met", or similar
   generic wording without concrete values and thresholds.
5. If available card parameters are missing from assistant_text, or missing
   parameters are not explicitly called out as unavailable, mark needs_repair=true.
"""


def assess_card_explanation(
    *,
    card_message: Dict[str, Any],
    assistant_text: str,
    fallback_text: str,
    client: LLMClient | None = None,
) -> CardExplanationQuality:
    obj = _json_chat(
        system=CARD_QUALITY_SYSTEM,
        payload={
            "card_message": card_message,
            "assistant_text": assistant_text,
            "fallback_text": fallback_text,
        },
        client=client,
        repair_label="card_quality",
    )
    return CardExplanationQuality(
        is_explaining_card=bool(obj.get("is_explaining_card", False)),
        grounded_to_card=bool(obj.get("grounded_to_card", False)),
        needs_repair=bool(obj.get("needs_repair", True)),
        reason=(str(obj.get("reason")).strip() if obj.get("reason") is not None else None),
    )


CARD_REPAIR_SYSTEM = """
你是 A 股短线股票助手。只根据 card_message 重写自然语言解释。

要求：
1. 解释卡片结论、关键字段含义、执行动作、风险边界或缺失数据。
2. 可以简短，但必须和卡片事实直接相关。
3. 不要提内部工具、模块、trace、JSON、调试字段。
4. 不要编造 card_message 之外的价格、公式、来源或交易结论。
"""
CARD_REPAIR_SYSTEM += """

Parameter repair rules:
1. When card_message has parameters, rewrite with parameter meaning, current
   value, threshold/expected condition, pass/fail state, and entry impact.
2. Cover available entry_low-entry_high, trigger_price, stop_price, take1/take2,
   rr_to_take1, slot_rel_vol, rs_index, rs_industry, price_vs_vwap, and vwap.
3. Explain RS as relative strength comparison, not RSI.
4. Do not write only generic wording such as "volume and RS confirm" or
   "wait for confirmation"; include concrete conditions and values.
5. If a parameter is missing from card_message, say it is missing and cannot be
   used to confirm entry. Do not invent it.
"""


def repair_card_explanation(
    *,
    card_message: Dict[str, Any],
    bad_text: str,
    fallback_text: str,
    client: LLMClient | None = None,
) -> str:
    client = client or LLMClient()
    ok, reason = client.available()
    if not ok:
        raise RuntimeError(f"LLM semantic repair unavailable: {reason}")
    response = client.chat(
        [
            {"role": "system", "content": CARD_REPAIR_SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "card_message": card_message,
                        "bad_text": bad_text,
                        "fallback_text": fallback_text,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        temperature=0.2,
    )
    return _extract_content(response)


ANNOUNCEMENT_RISK_SYSTEM = """
你是 A 股公告风险分类器。只输出 JSON，不输出解释。

根据 announcement_titles 判断近 30 日公告风险：
{
  "risk_level": "high|medium|none",
  "evidence": ["引用相关公告标题，最多 3 条"],
  "reason": "简短原因"
}

要求：
1. 不按固定关键词命中，按公告标题语义判断是否存在会影响交易的风险。
2. 没有明确风险时 risk_level="none"。
3. 只能引用输入列表里的标题。
"""


def assess_announcement_risk(
    announcements: List[Dict[str, Any]],
    *,
    client: LLMClient | None = None,
) -> AnnouncementRiskAssessment:
    titles = [str(item.get("title") or "").strip() for item in announcements if str(item.get("title") or "").strip()]
    if not titles:
        return AnnouncementRiskAssessment(risk_level=None, evidence=[], reason="no_announcements")
    obj = _json_chat(
        system=ANNOUNCEMENT_RISK_SYSTEM,
        payload={"announcement_titles": titles[:60]},
        client=client,
        repair_label="announcement_risk",
    )
    level = str(obj.get("risk_level") or "none").strip().lower()
    if level == "none":
        risk_level = None
    elif level in {"high", "medium"}:
        risk_level = level
    else:
        risk_level = None
    evidence_raw = obj.get("evidence") if isinstance(obj.get("evidence"), list) else []
    allowed = set(titles)
    evidence = [str(item).strip() for item in evidence_raw if str(item).strip() in allowed][:3]
    return AnnouncementRiskAssessment(
        risk_level=risk_level,
        evidence=evidence,
        reason=(str(obj.get("reason")).strip() if obj.get("reason") is not None else None),
    )
