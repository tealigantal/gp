from __future__ import annotations

import argparse
import json
import sys

from .core.logging import setup_logging
from .agent.agent import Agent
from .agent.router_factory import route_text


def _print_result(res) -> int:
    payload = {"ok": res.ok, "message": res.message}
    if res.data is not None:
        payload["data"] = res.data
    try:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except UnicodeEncodeError:
        # Fallback for consoles that cannot print UTF-8
        print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if res.ok else 1


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    agent = Agent()

    parser = argparse.ArgumentParser(prog="gp", description="gp assistant: chat-only interface")
    sub = parser.add_subparsers(dest="cmd")

    p_chat = sub.add_parser("chat", help="自然语言交互（LLM 路由）；支持 --repl 进入多轮模式")
    p_chat.add_argument("query", nargs="?", help="例如：recommend topk=3 date=2026-02-09")
    p_chat.add_argument("--repl", action="store_true", help="进入 REPL 多轮会话")

    p_bt = sub.add_parser("backtest", help="run backtest (placeholder)")
    p_bt.add_argument("--strategy", required=True)

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0

    if args.cmd == "chat":
        if args.repl or not args.query:
            print("欢迎使用 gp assistant 交互模式，输入 'exit' 退出。示例：recommend topk=3 date=2026-02-09")
            while True:
                try:
                    line = input("gp> ").strip()
                except EOFError:
                    break
                if not line:
                    continue
                if line.lower() in {"exit", "quit", ":q"}:
                    break
                route = route_text(line, agent.state)
                res = agent.run(route.tool, route.args)
                _print_result(res)
            return 0
        route = route_text(args.query, agent.state)
        res = agent.run(route.tool, route.args)
        return _print_result(res)
    if args.cmd == "backtest":
        res = agent.run("backtest", {"strategy": args.strategy})
        return _print_result(res)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
