from __future__ import annotations

from typing import Any

from ..core.types import ToolResult


def run_backtest(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    strategy = args.get("strategy")
    return ToolResult(
        ok=False,
        message=f"回测占位：策略 {strategy!r} 暂未实现",
        data=None,
    )

