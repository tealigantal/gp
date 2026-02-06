from __future__ import annotations

import argparse
from pathlib import Path

from .config import AssistantConfig
from .index.build_index import build_index
from .agent import ChatAgent
from .tools.results_reader import summarize_run


def main() -> None:
    p = argparse.ArgumentParser(prog="assistant", description="Repo-aware terminal assistant")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_chat = sub.add_parser("chat", help="Open REPL chat")
    p_chat.add_argument("--once", type=str, default=None, help="Run one-shot chat with the given text and exit")
    p_chat.add_argument("--print-state", action="store_true", help="Print state summary after actions")
    p_chat.add_argument("--reset-state", action="store_true", help="Reset state before starting chat")
    p_chat.add_argument("--verbose-tools", action="store_true", help="Print tool/exec/warn messages to terminal")
    p_chat.add_argument("--print-text", action="store_true", help="Print only the natural-language text field")
    p_chat.add_argument("--no-debug", action="store_true", help="Omit debug field in JSON output")

    p_index = sub.add_parser("index", help="Build or refresh local index")
    p_index.add_argument("--force", action="store_true")

    p_inspect = sub.add_parser("inspect", help="Quick summary of latest results run")

    args = p.parse_args()
    cfg = AssistantConfig.load()

    if args.cmd == "index":
        db_path = Path(cfg.rag.index_db)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        build_index(cfg, force=args.force)
        print("Index built at", db_path)
        return

    if args.cmd == "inspect":
        # Do not require LLM; directly summarize results
        print(summarize_run(Path(cfg.workspace_root) / 'results'))
        return

    if args.cmd == "chat":
        agent = ChatAgent(cfg)
        if getattr(args, 'reset_state', False):
            try:
                agent.state = type(agent.state)()  # type: ignore[attr-defined]
            except Exception:
                pass
        if getattr(args, 'print_state', False):
            try:
                agent.print_state = True  # type: ignore[attr-defined]
            except Exception:
                pass
        # Set verbose tools printing
        if getattr(args, 'verbose_tools', False):
            try:
                from .repl_render import set_verbose
                set_verbose(True)
            except Exception:
                pass
        if args.once:
            q = args.once
            resp = agent.respond_json(q, include_debug=(not args.no_debug))
            if args.print_text:
                print(resp.get('text', ''))
            else:
                import json as _json
                print(_json.dumps(resp, ensure_ascii=False))
            raise SystemExit(0)
        agent.repl(print_text_only=bool(args.print_text), include_debug=(not args.no_debug))
        

if __name__ == "__main__":
    main()
