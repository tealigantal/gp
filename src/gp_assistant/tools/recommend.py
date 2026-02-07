from __future__ import annotations

from typing import Any, List, Dict
import json

from ..core.types import ToolResult
from ..core.paths import configs_dir
from ..core.logging import logger
from ..llm_client import SimpleLLMClient


def _compose_with_llm(picks: List[Dict], market_context: Dict, *, explain: bool, need_trade_points: bool) -> Dict:
    cfg = configs_dir() / "llm.yaml"
    try:
        client = SimpleLLMClient(str(cfg), overrides={"max_tokens": 800, "temperature": 0.2})
    except Exception as e:  # noqa: BLE001
        logger.warning("推荐合成未启用(LLM不可用): %s", e)
        return {"narrative": None, "reasoning": None, "trade_points": None}
    sys_prompt = (
        "你是投研助手。你需要基于候选股票及当日市场要点生成‘结构化’推荐。\n"
        "仅输出 JSON，字段如下：{\"narrative\": string, \"reasoning\": string?, \"trade_points\": [{\"symbol\":string, \"buy_zone\":string, \"sell_zone\":string, \"stop_loss\":string, \"entry_timing\":string, \"notes\":string}]? }\n"
        "要求：\n- narrative 简洁清晰；\n- 若 explain=true 则补充 reasoning；\n- 若 need_trade_points=true 则给出每只候选的买卖点(区间/价位可给范围并标注不确定性)；\n- 不要输出 JSON 以外的任何内容。"
    )
    user_content = json.dumps({
        "candidates": picks,
        "market_context": {"summary": market_context.get("summary"), "sources": market_context.get("sources", [])},
        "explain": explain,
        "need_trade_points": need_trade_points,
    }, ensure_ascii=False)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_content},
    ]
    try:
        resp = client.chat(messages, json_response=True)
        content = resp.get("choices", [{}])[0].get("message", {}).get("content")
        data = json.loads(content) if content else {}
        return {
            "narrative": data.get("narrative"),
            "reasoning": data.get("reasoning"),
            "trade_points": data.get("trade_points"),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("推荐合成失败: %s", e)
        return {"narrative": None, "reasoning": None, "trade_points": None}


def run_recommend(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    candidates: List[Dict] = args.get("candidates", [])
    topk: int = int(args.get("topk", 3) or 3)
    context = args.get("market_context") or {}
    explain: bool = bool(args.get("explain") or False)
    need_tp: bool = bool(args.get("need_trade_points") or False)
    picks = candidates[:topk]
    llm_out = _compose_with_llm(picks, context, explain=explain, need_trade_points=need_tp)
    return ToolResult(
        ok=True,
        message=f"已生成推荐: {len(picks)} 只",
        data={
            "picks": picks,
            "market_context": {"summary": context.get("summary", ""), "sources": context.get("sources", [])},
            **llm_out,
        },
    )
