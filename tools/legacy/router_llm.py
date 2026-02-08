from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
import os
import json

from gp_assistant.core.paths import configs_dir
from gp_assistant.core.logging import logger
from gp_assistant.tools.registry import ToolRegistry  # type: ignore
from gp_assistant.llm_client import SimpleLLMClient


@dataclass
class Route:
    tool: str
    args: dict
    confidence: float = 0.0
    warnings: Optional[list[str]] = None


class LLMRouter:
    def __init__(self) -> None:
        self._client = None
        cfg_path = configs_dir() / "llm.yaml"
        try:
            if cfg_path.exists():
                self._client = SimpleLLMClient(str(cfg_path))
            else:
                if self._any_key():
                    logger.warning("缺少 configs/llm.yaml，LLM 路由不可用")
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM 客户端初始化失败: %s", e)
            self._client = None

    def route_text(self, query: str, state: Any) -> Route:  # noqa: ANN401
        if not self._client:
            return Route(tool="help", args={"reason": "LLM 未配置，缺少 configs/llm.yaml 或 API Key"}, confidence=0.0, warnings=["fallback: help"])
        tools = [
            {"name": "recommend", "args": {"date": "str?", "topk": "int?", "offset": "int?"}},
            {"name": "data", "args": {"symbol": "str", "start": "str?", "end": "str?"}},
            {"name": "market_info", "args": {"date": "str?"}},
            {"name": "explain", "args": {"symbol": "str?", "include_reason": "bool?", "strategy_only": "bool?"}},
            {"name": "pick", "args": {}},
            {"name": "backtest", "args": {"strategy": "str"}},
            {"name": "help", "args": {}},
        ]
        sys_prompt = (
            "你是一个严格的路由器。只输出 JSON，不要任何解释。\n"
            "输出字段严格为: {\"tool\": string, \"args\": object, \"confidence\": number?}.\n"
            f"可用工具与参数: {json.dumps(tools, ensure_ascii=False)}。\n"
            "严格输出 JSON，不要输出多余文本。"
        )
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": str(query or "").strip()},
        ]
        try:
            resp = self._client.chat(messages, json_response=True)
            content = resp.get("choices", [{}])[0].get("message", {}).get("content")
            data = json.loads(content) if content else {}
            tool = str(data.get("tool", "help"))
            args = data.get("args") or {}
            conf = float(data.get("confidence", 0.0)) if isinstance(data, dict) else 0.0
            return Route(tool=tool, args=args, confidence=conf)
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM 路由失败，返回 help: %s", e)
            return Route(tool="help", args={"reason": "路由失败"}, confidence=0.0)

    @staticmethod
    def _any_key() -> bool:
        return bool(
            os.getenv("LLM_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("UPSTREAM_API_KEY")
        )

