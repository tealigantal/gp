from __future__ import annotations

from typing import Any, List, Dict

from ..core.types import ToolResult


def run_rank(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    """Rank candidates using a simple heuristic (placeholder)."""
    candidates: List[Dict] = args.get("candidates") or []
    # Keep as-is; in the future, use LLM ranking
    return ToolResult(ok=True, message=f"排名完成: {len(candidates)} 项", data={"ranked": candidates})

