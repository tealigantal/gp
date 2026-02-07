from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Any

from ..core.types import ToolResult


Runner = Callable[[dict, Any], ToolResult]


@dataclass
class Tool:
    name: str
    description: str
    args_schema: dict  # minimal; future: pydantic/dataclass
    run: Runner


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"tool not found: {name}")
        return self._tools[name]

    def list(self) -> Dict[str, Tool]:
        return dict(self._tools)

