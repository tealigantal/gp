from __future__ import annotations

from typing import Any

from gp_assistant.core.types import ToolResult
from gp_assistant.core.logging import logger
from gp_assistant.providers.factory import provider_health
from gp_assistant.agent.state import State
from gp_assistant.tools.registry import Tool, ToolRegistry
from gp_assistant.tools import market_data, universe, signals, rank, backtest, explain
from gp_assistant.tools import strategy_score, market_info, recommend
from tools.legacy.router_factory import route_text


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
    reg.add(
        Tool(
            name="strategy_score",
            description="对候选池进行策略评分（占位）",
            args_schema={"symbols": "list[str]", "topk": "int?", "offset": "int?"},
            run=strategy_score.run_strategy_score,
        )
    )
    reg.add(
        Tool(
            name="market_info",
            description="当日市场信息摘要（占位）",
            args_schema={"date": "str?"},
            run=market_info.run_market_info,
        )
    )
    reg.add(
        Tool(
            name="recommend",
            description="汇总评分与市场摘要生成推荐（占位）",
            args_schema={"candidates": "list", "topk": "int?", "market_context": "dict?", "explain": "bool?", "need_trade_points": "bool?"},
            run=recommend.run_recommend,
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
            uni = self.registry.get("universe").run({}, self.state)
            if not uni.ok:
                return uni
            symbols = uni.data.get("symbols", []) if uni.data else []
            candidates = [{"symbol": sym} for sym in symbols]
            rres = self.registry.get("rank").run({"candidates": candidates}, self.state)
            return ToolResult(ok=True, message=rres.message, data=rres.data)

        if tool_name == "recommend":
            topk = int(args.get("topk", 3) or 3)
            offset = int(args.get("offset", 0) or 0)
            date = args.get("date")
            uni = self.registry.get("universe").run({}, self.state)
            if not uni.ok:
                return uni
            symbols = uni.data.get("symbols", []) if uni.data else []
            score_res = self.registry.get("strategy_score").run({"symbols": symbols, "topk": topk, "offset": offset}, self.state)
            if not score_res.ok:
                return score_res
            mi_res = self.registry.get("market_info").run({"date": date}, self.state)
            if not mi_res.ok:
                return mi_res
            cand = score_res.data.get("candidates", []) if score_res.data else []
            ctx = mi_res.data or {}
            rec_res = self.registry.get("recommend").run({"candidates": cand, "topk": topk, "market_context": ctx}, self.state)
            try:
                self.state.context["last_recommend"] = {
                    "topk": topk,
                    "offset": offset,
                    "symbols": [c.get("symbol") for c in cand],
                    "date": date,
                }
            except Exception:
                pass
            return rec_res

        tool = self.registry.get(tool_name)
        res = tool.run(args, self.state)
        try:
            self.state.history.append({"tool": tool_name, "args": args, "ok": res.ok})
            if len(self.state.history) > 10:
                self.state.history = self.state.history[-10:]
        except Exception:
            pass
        return res

    def render_help(self) -> str:
        hc = provider_health()
        lines = [
            "接口: chat (LLM 路由，仅此一个)",
            "提示: 在容器中运行 `python -m gp_assistant chat --repl` 进入多轮模式",
            f"数据源: {hc}",
        ]
        return "\n".join(lines)

