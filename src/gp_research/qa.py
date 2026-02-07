from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .schemas import RecommendationItem, RecommendationResponse


def compose_response(
    *,
    provider_hint: Optional[str],
    llm_client,  # may be None or SimpleLLMClient
    user_question: str,
    user_profile: Dict[str, Any],
    market_summary: str,
    champion: Dict[str, Any],
    picks: List[Dict[str, Any]],
    run_summaries: List[Dict[str, Any]],
) -> RecommendationResponse:
    # Try LLM if provided and allowed
    use_llm = llm_client is not None and (provider_hint or "").lower() not in ("mock", "fallback")
    if use_llm:
        try:
            sys_prompt = (
                "你是投研助手。输出严格为JSON且满足以下字段：\n"
                "provider, summary, chosen_strategy{name,reason}, recommendations[list of {code,name?,direction,thesis,entry?,stop_loss?,take_profit?,position_sizing?}], risks[list], assumptions[list]。\n"
                "注意：不得输出多余文本。"
            )
            content = {
                "question": user_question,
                "profile": user_profile,
                "market_summary": market_summary,
                "champion": champion,
                "picks": picks,
                "run_summaries": run_summaries,
            }
            resp = llm_client.chat([
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": __import__("json").dumps(content, ensure_ascii=False)},
            ], json_response=True)
            txt = resp.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            data = __import__("json").loads(txt)
            # Basic validation
            if not isinstance(data, dict) or not data.get("recommendations"):
                raise RuntimeError("invalid llm response")
            # Build schema
            items = [RecommendationItem(**it) for it in data.get("recommendations", [])]
            return RecommendationResponse(
                provider=data.get("provider", "llm"),
                summary=str(data.get("summary", "")),
                chosen_strategy=dict(data.get("chosen_strategy", champion)),
                recommendations=items,
                risks=list(data.get("risks", [])),
                assumptions=list(data.get("assumptions", [])),
            )
        except Exception:
            pass

    # Fallback rule template
    items: List[RecommendationItem] = []
    for p in picks:
        items.append(
            RecommendationItem(
                code=str(p.get("ts_code")),
                name=None,
                direction="long",
                thesis=f"基于{champion.get('name','冠军策略')}的候选。",
                entry="分批入场，注意量价配合",
                stop_loss="跌破关键支撑",
                take_profit="冲高回落或达预期",
                position_sizing=f"不超过等权的1/{max(1,len(picks))}"
            )
        )
    return RecommendationResponse(
        provider="fallback",
        summary=market_summary,
        chosen_strategy={"name": champion.get("name", "unknown"), "reason": champion.get("reason", "rule")},
        recommendations=items,
        risks=["市场风格判断可能偏差", "数据可能不完整，仅供参考"],
        assumptions=["使用简化回测与规则模板", "未考虑交易限制与滑点细节"],
    )

