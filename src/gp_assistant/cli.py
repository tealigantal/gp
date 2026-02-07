from __future__ import annotations

import argparse
import json
import sys

from .core.logging import setup_logging
from .agent.agent import Agent
from .agent.router import route_text


def _print_result(res) -> int:
    payload = {"ok": res.ok, "message": res.message}
    if res.data is not None:
        payload["data"] = res.data
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if res.ok else 1


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    agent = Agent()

    parser = argparse.ArgumentParser(prog="gp", description="gp assistant: single-entry agent")
    sub = parser.add_subparsers(dest="cmd")

    p_chat = sub.add_parser("chat", help="free text; route to a tool")
    p_chat.add_argument("query", nargs="?", default="help", help="query like: data 000001 start=2024-01-01")

    p_data = sub.add_parser("data", help="fetch market data")
    p_data.add_argument("--symbol", required=True)
    p_data.add_argument("--start")
    p_data.add_argument("--end")

    p_pick = sub.add_parser("pick", help="pick candidates")

    p_bt = sub.add_parser("backtest", help="run backtest (placeholder)")
    p_bt.add_argument("--strategy", required=True)

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0

    if args.cmd == "chat":
        route = route_text(args.query)
        res = agent.run(route.tool, route.args)
        return _print_result(res)
    if args.cmd == "data":
        res = agent.run("data", {"symbol": args.symbol, "start": args.start, "end": args.end})
        return _print_result(res)
    if args.cmd == "pick":
        res = agent.run("pick", {})
        return _print_result(res)
    if args.cmd == "backtest":
        res = agent.run("backtest", {"strategy": args.strategy})
        return _print_result(res)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

