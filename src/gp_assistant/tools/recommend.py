from __future__ import annotations

from typing import Any, List, Dict
import json

from ..core.types import ToolResult
from ..core.paths import configs_dir
from ..core.logging import logger
from ..llm_client import SimpleLLMClient
from ..recommend.agent import run as recommend_run
from ..observe.degrade import apply_tradeable_flag


def _compose_missing(reason: str | None = None) -> Dict:
    return {"narrative": None, "reasoning": None, "trade_points": None, "missing": reason or "llm_unavailable"}


def _compose_with_llm(picks: List[Dict], market_context: Dict, *, explain: bool, need_trade_points: bool) -> Dict:
    cfg = configs_dir() / "llm.yaml"
    try:
        client = SimpleLLMClient(str(cfg), overrides={"max_tokens": 800, "temperature": 0.2})
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM unavailable: %s", e)
        return {"narrative": None, "reasoning": None, "trade_points": None}
    sys_prompt = ("Output only JSON with keys: narrative, reasoning?, trade_points?.\n")
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
        logger.warning("LLM composition failed: %s", e)
        return {"narrative": None, "reasoning": None, "trade_points": None}


def run_recommend(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    """Generate recommendations via the main engine and return structured result."""
    topk: int = int(args.get("topk", 3) or 3)
    date = args.get("date")
    risk_profile = str(args.get("risk_profile", "normal"))
    use_llm = bool(args.get("use_llm", False))
    explain: bool = bool(args.get("explain") or False)
    need_tp: bool = bool(args.get("need_trade_points") or False)

    symbols = args.get("symbols")
    universe = "symbols" if symbols else "auto"
    try:
        payload = recommend_run(date=date, topk=topk, universe=universe, symbols=symbols, risk_profile=risk_profile)
        picks: List[Dict] = list(payload.get("picks", []))
        context = payload.get("env", {})
        if use_llm:
            composed = _compose_with_llm(picks, context, explain=explain, need_trade_points=need_tp)
        else:
            composed = _compose_missing("llm_disabled")
        data = {
            "picks": picks,
            "market_context": context,
            **composed,
            "debug": payload.get("debug", {}),
            "tradeable": bool(payload.get("tradeable", False)),
        }
        tr = ToolResult(ok=True, message=f"generated {len(picks)} picks", data=data)
        tr = apply_tradeable_flag(tr)
        return tr
    except Exception as e:  # noqa: BLE001
        logger.error("recommend engine failed: %s", e)
        tr = ToolResult(ok=False, message=f"推荐失败: {e}", data={"error": str(e)})
        tr = apply_tradeable_flag(tr)
        return tr



