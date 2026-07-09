from __future__ import annotations

import argparse
import json

import uvicorn

from .evidence.daily_freshness import audit_daily_freshness
from .gateway.app import app
from .runtime.diagnostics import diagnose_runtime_slot_state
from .runtime.turn_loop import run_turn_sync
from .worker import reconcile_runtime_state, run_runtime_loop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gp-assistant")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="run FastAPI server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)

    sub.add_parser("runtime-loop", help="run the unified market runtime worker loop")
    sub.add_parser("daily-loop", help="compatibility alias for runtime-loop")
    sub.add_parser("rebuild-daybook", help="generate today daily plan artifact")
    sub.add_parser("postclose-archive", help="archive post-close state")
    sub.add_parser("audit-daily-freshness", help="audit daily freshness and stale symbols")

    p_diagnose_slot = sub.add_parser("diagnose-slot-state", help="read current slot/daily freshness state without publishing")
    p_diagnose_slot.add_argument("--trade-day", default=None)
    p_diagnose_slot.add_argument("--symbols", default=None, help="comma-separated symbols to inspect from daily cache")

    p_chat = sub.add_parser("chat", help="single-turn chat")
    p_chat.add_argument("message")
    p_chat.add_argument("--session-id", default=None)

    args = parser.parse_args(argv)
    if args.cmd == "serve":
        uvicorn.run(app, host=args.host, port=args.port)
        return 0
    if args.cmd in {"runtime-loop", "daily-loop"}:
        run_runtime_loop()
        return 0
    if args.cmd == "rebuild-daybook":
        print(json.dumps(reconcile_runtime_state(operation="rebuild_daybook"), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "postclose-archive":
        print(json.dumps(reconcile_runtime_state(operation="postclose_archive"), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-daily-freshness":
        print(json.dumps(audit_daily_freshness(), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "diagnose-slot-state":
        symbols = [item.strip() for item in str(args.symbols or "").split(",") if item.strip()] or None
        print(json.dumps(diagnose_runtime_slot_state(trade_day=args.trade_day, symbols=symbols), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "chat":
        out = run_turn_sync(session_id=args.session_id, user_message=args.message)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
