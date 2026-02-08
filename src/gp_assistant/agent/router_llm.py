from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
import os
import json

from ..core.paths import configs_dir
from ..core.logging import logger
from ..tools.registry import ToolRegistry  # type: ignore
from ..llm_client import SimpleLLMClient


@dataclass
class Route:
    tool: str
    args: dict
    confidence: float = 0.0
    warnings: Optional[list[str]] = None


class LLMRouter:
    """LLM-only router stub.

    - If no LLM key is configured, returns help with reason.
    - This is a thin placeholder that can be extended to call your LLM/proxy.
    """

    def __init__(self) -> None:
        self._client = None
        # Try to initialize from configs/llm.yaml; fall back to env-only detection
        cfg_path = configs_dir() / "llm.yaml"
        try:
            if cfg_path.exists():
                self._client = SimpleLLMClient(str(cfg_path))
            else:
                # fallback check: if any key present, we still run but use default openai base
                if self._any_key():
                    # Construct a minimal config override by writing a temp in-memory values is not supported
                    # So rely on llm.yaml existing; otherwise we cannot safely know base_url/model.
                    logger.warning("缺少 configs/llm.yaml，LLM 路由不可用")
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM 客户端初始化失败: %s", e)
            self._client = None

    def route_text(self, query: str, state: Any) -> Route:  # noqa: ANN401
        if not self._client:
            return Route(
                tool="help",
                args={"reason": "LLM 未配置，缺少 configs/llm.yaml 或 API Key"},
                confidence=0.0,
                warnings=["fallback: help"],
            )
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
            "多轮对话策略：\n"
            "1) 当用户未明确工具且与上一轮意图相关，默认延续上一轮 tool，并继承必要参数（如 date/topk/offset）。\n"
            "2) 当用户表达‘更多/其他/换/继续’等追问且上一轮为 recommend：设置 args.offset = last.offset + last.topk（分页获取下一批）；保留 last.topk 与 last.date。\n"
            "3) 当用户追问‘为什么/理由/原因’：设置 args.explain = true。\n"
            "4) 当用户要求‘买卖点/支撑位/阻力位/止损/入手时机/需要发给我’：设置 args.need_trade_points = true。\n"
            "5) 参数缺失时尽量从最近上下文补全；仍不确定时返回 help，并在 args.question 中提出你需要的关键信息。\n"
            "严格输出 JSON，不要输出多余文本。"
        )
        # Include short conversation context derived from prior routes (last 5)
        ctx_items = []
        try:
            hist = getattr(state, "history", []) or []
            ctx_items = hist[-5:]
        except Exception:
            ctx_items = []
        last_rec = {}
        try:
            last_rec = getattr(state, "context", {}).get("last_recommend", {}) or {}
        except Exception:
            last_rec = {}
        ctx_note = json.dumps({"recent_routes": ctx_items, "last_recommend": last_rec}, ensure_ascii=False)
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "system", "content": f"对话上下文: {ctx_note}"},
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
