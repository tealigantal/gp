from __future__ import annotations

from typing import Any

from ..core.types import ToolResult
from ..core.logging import logger
from ..providers.factory import provider_health
from .state import State
from ..tools.registry import Tool, ToolRegistry
from ..tools import market_data, universe, signals, rank, backtest, explain


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.add(
        Tool(
            name="data",
            description="获取行情数据",
            args_schema={"symbol": "str", "start": "str?", "end": "str?"},
            run=market_data.run_data,
        )
    )
    reg.add(
        Tool(
            name="universe",
            description="获取候选池",
            args_schema={},
            run=universe.run_universe,
        )
    )
    reg.add(
        Tool(
            name="signals",
            description="计算指标信号",
            args_schema={"df": "DataFrame"},
            run=signals.run_signals,
        )
    )
    reg.add(
        Tool(
            name="rank",
            description="候选排序",
            args_schema={"candidates": "list"},
            run=rank.run_rank,
        )
    )
    reg.add(
        Tool(
            name="backtest",
            description="回测（占位）",
            args_schema={"strategy": "str"},
            run=backtest.run_backtest,
        )
    )
    reg.add(
        Tool(
            name="explain",
            description="解释（占位）",
            args_schema={"topic": "str"},
            run=explain.run_explain,
        )
    )
    return reg


class Agent:
    def __init__(self, state: State | None = None, registry: ToolRegistry | None = None):
        self.state = state or State()
        self.registry = registry or build_registry()

    def run(self, tool_name: str, args: dict) -> ToolResult:
        if tool_name == "help":
            return ToolResult(ok=True, message=self.render_help())

        if tool_name == "pick":
            # minimal pick pipeline: universe -> data (per symbol) -> rank
            uni = self.registry.get("universe").run({}, self.state)
            if not uni.ok:
                return uni
            symbols = uni.data.get("symbols", []) if uni.data else []
            candidates = [{"symbol": sym} for sym in symbols]
            rres = self.registry.get("rank").run({"candidates": candidates}, self.state)
            return ToolResult(ok=True, message=rres.message, data=rres.data)

        tool = self.registry.get(tool_name)
        res = tool.run(args, self.state)
        return res

    def render_help(self) -> str:
        hc = provider_health()
        lines = [
            "可用子命令:",
            " - chat: 文本路由模式 (data/pick/backtest)",
            " - data --symbol 000001 [--start YYYY-MM-DD --end YYYY-MM-DD]",
            " - pick",
            " - backtest --strategy NAME",
            f"数据源: {hc}",
        ]
        return "\n".join(lines)
