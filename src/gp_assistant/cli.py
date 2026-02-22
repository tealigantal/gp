from __future__ import annotations

import argparse
import json
import sys

from .chat.orchestrator import handle_message


def _chat_once(message: str, session_id: str | None = None) -> int:
    try:
        out = handle_message(session_id, message, None)
        print(json.dumps(out, ensure_ascii=True))
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}")
        return 1


def _chat_repl() -> int:
    print("gp-assistant chat (stdin). Ctrl+C or /quit to exit.")
    sid: str | None = None
    try:
        while True:
            line = input("you> ").strip()
            if not line or line in {"/q", "/quit", ":q"}:
                break
            out = handle_message(sid, line, None)
            sid = out.get("session_id", sid)
            reply = out.get("reply", "")
            print(f"agent> {reply}")
        return 0
    except KeyboardInterrupt:
        print()
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gp-assistant")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_chat = sub.add_parser("chat", help="聊天：交互式或单次")
    p_chat.add_argument("--once", metavar="TEXT", help="单次对话，输出 JSON")
    p_chat.add_argument("--session", help="会话ID（可选）")

    args = parser.parse_args(argv)

    if args.cmd == "chat":  # type: ignore[attr-defined]
        if getattr(args, "once", None):
            return _chat_once(args.once, getattr(args, "session", None))
        return _chat_repl()

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
