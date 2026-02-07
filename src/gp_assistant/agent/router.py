from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Route:
    tool: str
    args: dict


def route_text(query: str) -> Route:
    q = (query or "").strip().lower()
    # minimal rules: check leading keyword
    if q.startswith("data"):
        # data 000001 start=2024-01-01 end=2024-02-01
        parts = q.split()
        symbol = parts[1] if len(parts) > 1 else ""
        args = {"symbol": symbol}
        for p in parts[2:]:
            if "=" in p:
                k, v = p.split("=", 1)
                args[k] = v
        return Route(tool="data", args=args)
    if q.startswith("pick"):
        return Route(tool="pick", args={})
    if q.startswith("backtest"):
        return Route(tool="backtest", args={})
    return Route(tool="help", args={})

