from __future__ import annotations

from typing import Any

from ..core.types import ToolResult
from ..core.config import load_config


def run_universe(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    cfg = load_config()
    symbols = cfg.default_universe
    return ToolResult(
        ok=True,
        message=f"候选池共 {len(symbols)} 只",
        data={"symbols": symbols},
    )

