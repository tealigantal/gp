# 简介：常用类型别名与结构定义，便于类型标注与静态检查。
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ToolResult:
    ok: bool
    message: str
    data: Any | None = None
    # Optional tradeability flag for top-level visibility of degradations
    tradeable: bool | None = None


JSONDict = Dict[str, Any]
