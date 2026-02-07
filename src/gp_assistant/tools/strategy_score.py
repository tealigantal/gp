from __future__ import annotations

from typing import Any, List, Dict

from ..core.types import ToolResult


def _score_symbol(sym: str) -> float:
    # Deterministic placeholder scoring: sum of digits mod 10 / 10
    s = sum(int(c) for c in sym if c.isdigit())
    return (s % 10) / 10.0


def run_strategy_score(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    symbols: List[str] = args.get("symbols", [])
    topk: int = int(args.get("topk", 3) or 3)
    offset: int = int(args.get("offset", 0) or 0)
    if not symbols:
        return ToolResult(ok=True, message="无候选可评分", data={"candidates": []})
    scored: List[Dict] = [{"symbol": s, "score": _score_symbol(s)} for s in symbols]
    scored.sort(key=lambda x: x["score"], reverse=True)
    start = max(0, offset)
    end = start + (topk or len(scored))
    sliced = scored[start:end]
    return ToolResult(
        ok=True,
        message=f"已评分 {len(scored)} 只，返回区间[{start}:{end}) 共 {len(sliced)}",
        data={"candidates": sliced, "offset": start, "total": len(scored)},
    )
