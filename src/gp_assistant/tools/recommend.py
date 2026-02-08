# 简介：工具 - 调用“荐股主引擎”并输出结构化结果，支持确定性说明（可选LLM增强）。
from __future__ import annotations

from typing import Any, List, Dict
import json

from ..core.types import ToolResult
from ..core.paths import configs_dir
from ..core.logging import logger
from ..llm_client import SimpleLLMClient
from ..recommend.agent import run as recommend_run


def _compose_missing(reason: str | None = None) -> Dict:
    return {"narrative": None, "reasoning": None, "trade_points": None, "missing": reason or "llm_unavailable"}


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
    """基于主引擎生成推荐结果。

    支持两种用法：
    1) 直接指定 `symbols`（或使用默认池），由主引擎产生候选、统计与打分；
    2) 传入已有 `candidates` 时，也会尽量补齐统计并按打分排序（未来版本）。
    """
    topk: int = int(args.get("topk", 3) or 3)
    date = args.get("date")
    risk_profile = str(args.get("risk_profile", "normal"))
    use_llm = bool(args.get("use_llm", False))
    explain: bool = bool(args.get("explain") or False)
    need_tp: bool = bool(args.get("need_trade_points") or False)

    # 优先走主引擎（可选 symbols）；否则退化到 candidates 列表
    symbols = args.get("symbols")
    universe = "symbols" if symbols else "auto"
    try:
        payload = recommend_run(date=date, topk=topk, universe=universe, symbols=symbols, risk_profile=risk_profile)
        picks: List[Dict] = list(payload.get("picks", []))
        context = payload.get("env", {})
        # 说明生成：仅在 use_llm=true 时调用；否则返回缺失标记
        if use_llm:
            composed = _compose_with_llm(picks, context, explain=explain, need_trade_points=need_tp)
        else:
            composed = _compose_missing("llm_disabled")
        data = {
            "picks": picks,
            "market_context": context,
            **composed,
        }
        return ToolResult(ok=True, message=f"已生成推荐: {len(picks)} 只", data=data)
    except Exception as e:  # noqa: BLE001
        logger.error("主引擎推荐失败: %s", e)
        return ToolResult(ok=False, message=f"推荐失败: {e}", data={"error": str(e)})
