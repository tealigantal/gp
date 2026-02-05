from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List

from .config import AssistantConfig
from .llm_client import SimpleLLMClient
from .session_store import SessionStore
from .index.store import IndexStore
from .tools import repo_search
from .tools.results_reader import summarize_run
from .tools.doctor_reader import read_doctor, summarize_doctor
from .tools.gpbt_runner import run_gpbt
from .tools.gp_runner import run_gp


SYS_PROMPT = (
    "你是仓库内置的研究助手。回答前应尽量检索仓库事实（README、configs、src、策略yaml、results/）后作答。"\
    "当你声称‘我读了某文件 / 执行了某命令’，会话日志中必须包含对应的工具调用记录。"\
    "仅允许受控动作：python gpbt.py 与 python gp.py 的白名单子命令。禁止任意Shell。"\
    "优先基于 compare_strategies.csv、doctor_report.json、metrics.json 作答；缺内容时再建议下一步命令。"
)


class ChatAgent:
    def __init__(self, cfg: AssistantConfig):
        self.cfg = cfg
        self.repo = cfg.workspace_root
        self.sessions_dir = self.repo / 'store' / 'assistant' / 'sessions'
        self.session = SessionStore(self.sessions_dir)
        self.index = IndexStore(Path(cfg.rag.index_db))
        self.llm = SimpleLLMClient(cfg.llm.llm_config_file, {
            'temperature': cfg.llm.temperature,
            'max_tokens': cfg.llm.max_tokens,
            'timeout': cfg.llm.timeout,
        })

    def _gather_context(self, q: str) -> str:
        # Fulltext hits
        hits = self.index.search(q, topk=6)
        if not hits:
            # fallback to simple scan
            hits = repo_search.search(self.repo, q, self.cfg.rag.include_globs, self.cfg.rag.exclude_globs)
        ctx = []
        for path, snip in hits:
            self.session.append('tool', 'repo_search', {'path': path, 'bytes': len(snip)})
            ctx.append(f"[FILE] {path}\n{snip}\n")
        # Attach latest results summary if relevant
        if any(k in q.lower() for k in ['compare_strategies', '策略', '回测', '收益', '胜率']):
            txt = summarize_run(self.repo / 'results')
            if txt:
                self.session.append('tool', 'results_reader', {'summary_len': len(txt)})
                ctx.append("[RESULTS]\n" + txt)
        if any(k in q.lower() for k in ['doctor', '分钟', '缺失', '诊断']):
            rep = read_doctor(self.repo / 'results')
            summ = summarize_doctor(rep)
            if summ:
                self.session.append('tool', 'doctor_reader', {'keys': list(rep.get('checks', {}).keys()) if rep else []})
                ctx.append("[DOCTOR]\n" + summ)
        return "\n\n".join(ctx)

    def _chat_once(self, user: str) -> str:
        ctx = self._gather_context(user)
        sys_msg = {'role': 'system', 'content': SYS_PROMPT}
        usr = {'role': 'user', 'content': f"问题：{user}\n\n可用上下文（可能不全）：\n{ctx}"}
        self.session.append('user', user)
        resp = self.llm.chat([sys_msg, usr], json_response=False)
        try:
            content = resp['choices'][0]['message']['content']
        except Exception:
            content = str(resp)
        self.session.append('assistant', content)
        return content

    def repl(self) -> None:
        print("Repo assistant ready. Type your question; Ctrl+C to exit.")
        while True:
            try:
                q = input('>>> ').strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not q:
                continue
            # Quick action shorthands
            if q.startswith('!gpbt '):
                self._run_gpbt_from_line(q[len('!gpbt '):])
                continue
            if q.startswith('!gp '):
                self._run_gp_from_line(q[len('!gp '):])
                continue
            ans = self._chat_once(q)
            print(ans)

    def _run_gpbt_from_line(self, line: str) -> None:
        parts = line.split()
        if not parts:
            return
        sub = parts[0]
        args = parts[1:]
        if sub not in self.cfg.tools.gpbt_allow_subcommands:
            print("Refused: not allowed. Allowed:", self.cfg.tools.gpbt_allow_subcommands)
            return
        code, out, err, dt = run_gpbt(sys.executable, self.repo, sub, args, self.cfg.tools.gpbt_allow_subcommands)
        self.session.append('tool', 'gpbt', {'cmd': [sub] + args, 'code': code, 'stderr': err[:2000], 'seconds': dt})
        print(out)
        if err:
            print(err, file=sys.stderr)

    def _run_gp_from_line(self, line: str) -> None:
        parts = line.split()
        if not parts:
            return
        sub = parts[0]
        args = parts[1:]
        if sub not in self.cfg.tools.gp_allow_subcommands:
            print("Refused: not allowed. Allowed:", self.cfg.tools.gp_allow_subcommands)
            return
        code, out, err, dt = run_gp(sys.executable, self.repo, sub, args, self.cfg.tools.gp_allow_subcommands)
        self.session.append('tool', 'gp', {'cmd': [sub] + args, 'code': code, 'stderr': err[:2000], 'seconds': dt})
        print(out)
        if err:
            print(err, file=sys.stderr)

    def results_summary_latest(self) -> str:
        return summarize_run(self.repo / 'results')

