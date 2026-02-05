from __future__ import annotations

import argparse
from pathlib import Path

from .config import AssistantConfig
from .index.build_index import build_index
from .agent import ChatAgent


def main() -> None:
    p = argparse.ArgumentParser(prog="assistant", description="Repo-aware terminal assistant")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_chat = sub.add_parser("chat", help="Open REPL chat")

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
        agent = ChatAgent(cfg)
        txt = agent.results_summary_latest()
        print(txt)
        return

    if args.cmd == "chat":
        agent = ChatAgent(cfg)
        agent.repl()


if __name__ == "__main__":
    main()

