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
        if args.once:
            q = args.once
            # Natural language triggers are handled inside repl; emulate here
            if any(k in q for k in ['荐股', '推荐', '选股', 'topk', 'TopK', 'TOPK']) or q.startswith('/pick'):
                # Route to pick action by parsing minimal options if present
                from .actions.pick import pick_once
                date = None
                topk = 3
                template = 'momentum_v1'
                # crude parse for YYYYMMDD and topk
                import re
                m = re.search(r"(20\d{6})", q)
                if m:
                    date = m.group(1)
                mk = re.search(r"top\s*([0-9]+)", q, re.IGNORECASE)
                if mk:
                    topk = int(mk.group(1))
                try:
                    res = pick_once(Path(cfg.workspace_root), agent.session, date=date, topk=topk, template=template)
                    print(agent._format_pick_result(res))
                    raise SystemExit(0)
                except Exception as e:
                    print('Pick failed:', e)
                    raise SystemExit(1)
            else:
                out = agent._chat_once(q)
                print(out)
                raise SystemExit(0)
        agent.repl()
        

if __name__ == "__main__":
    main()
