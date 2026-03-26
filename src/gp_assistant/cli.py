from __future__ import annotations

import argparse
import json
import uvicorn

from .gateway.app import app
from .runtime.turn_loop import run_turn_sync
from .book.engine import sync_book_once


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gp-assistant")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="run FastAPI server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)

    p_worker = sub.add_parser("pulse", help="advance market book to latest 5m")

    p_chat = sub.add_parser("chat", help="single-turn chat")
    p_chat.add_argument("message")
    p_chat.add_argument("--session-id", default=None)

    args = parser.parse_args(argv)
    if args.cmd == "serve":
        uvicorn.run(app, host=args.host, port=args.port)
        return 0
    if args.cmd == "pulse":
        out = sync_book_once()
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "chat":
        out = run_turn_sync(session_id=args.session_id, user_message=args.message)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    return 1
