# 简介：工具 - 解释器，将结构化推荐转成说明文本或用于可视化的字段。
from __future__ import annotations

from typing import Any

from ..core.types import ToolResult


def run_explain(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    topic = args.get("topic", "")
    return ToolResult(ok=True, message=f"解释占位: {topic}")
