from __future__ import annotations

"""Operational entry points for the single-protocol product."""

import argparse
import json

import uvicorn

from .agent_store import AgentStore
from .chat_agent import run_chat_turn
from .gateway.app import app
from .runtime.utils import gen_id
from .serenity.worker import run_serenity_loop, run_serenity_once, serenity_status
from .worker import run_runtime_loop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gp-assistant")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="run the single-protocol API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("runtime-loop", help="publish RecommendationSnapshot.v1 from the selection worker")
    sub.add_parser("serenity-loop", help="run the advisory official-announcement collector")
    sub.add_parser("serenity-once", help="run one bounded Serenity collection round")
    sub.add_parser("serenity-status", help="read Serenity experiment status")
    chat = sub.add_parser("chat", help="submit one unified chat turn")
    chat.add_argument("message")
    chat.add_argument("--session-id", default=None)
    args = parser.parse_args(argv)
    if args.cmd == "serve":
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.cmd == "runtime-loop":
        run_runtime_loop()
    elif args.cmd == "serenity-loop":
        run_serenity_loop()
    elif args.cmd == "serenity-once":
        print(json.dumps(run_serenity_once(), ensure_ascii=False, indent=2))
    elif args.cmd == "serenity-status":
        print(json.dumps(serenity_status(), ensure_ascii=False, indent=2))
    elif args.cmd == "chat":
        print(json.dumps(run_chat_turn(session_id=args.session_id, client_turn_id=gen_id("cli"), user_message=args.message, store=AgentStore()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
