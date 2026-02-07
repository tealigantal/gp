from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ToolResult:
    ok: bool
    message: str
    data: Any | None = None


JSONDict = Dict[str, Any]

